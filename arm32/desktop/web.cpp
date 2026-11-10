// HTTP for the game: the Java side of Unity's WWW and UnityWebRequest, as Unity 5.6's own Java has them (the callbacks
// in its order, with its arguments), on the player's own HTTP/1.1 client (http.cpp), which asks for and inflates
// compressed answers as a phone's HttpURLConnection does. The game talks to its server over plain HTTP; HTTPS is refused
// with the error a failed handshake gives.
#include "player.h"

#include "http.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <strings.h>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;
// The HTTP client's names (http.h).
using net::Failure;
using net::Http;
using net::Url;
using net::parse_url;

// ---------------------------------------------------------------------------------------------------------------------
// Local URLs, which Java's own URL classes read: file:///path, and jar:file:///path.apk!/entry (Unity's StreamingAssets on
// Android are inside the APK, and the game reads its string tables from there through WWW).

// %XX as bytes.
std::string percent_decoded(const std::string& s) {
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

// The path of a file: URL ("file:///a/b" and "file:/a/b" are both /a/b).
std::string file_path(const std::string& url) {
    std::string p = url.substr(5);
    if (p.rfind("//", 0) == 0) p = p.substr(2);
    return percent_decoded(p);
}

bool is_local(const std::string& url) {
    auto starts = [&url](const char* s) { return strncasecmp(url.c_str(), s, std::strlen(s)) == 0; };
    return starts("file:") || starts("jar:");
}

// A local URL's contents: an entry of the app's APK for jar:, the file for file:.
bool read_local(const std::string& url, std::vector<std::uint8_t>& out, Failure& f) {
    if (strncasecmp(url.c_str(), "jar:", 4) == 0) {
        std::size_t bang = url.find("!/");
        if (bang == std::string::npos || strncasecmp(url.c_str() + 4, "file:", 5) != 0) {
            f = Failure{5, "java.net.MalformedURLException: " + url};
            return false;
        }
        std::string archive = file_path(url.substr(4, bang - 4)), entry = percent_decoded(url.substr(bang + 2));
        // Only the app's own APK is a jar the game reads.
        if (host_of(archive) != app().host_apk || !apk_entry(entry, out)) {
            f = Failure{2, "java.io.FileNotFoundException: " + url};
            return false;
        }
        return true;
    }
    std::string host = host_of(file_path(url));
    std::ifstream in(utf8_path(host), std::ios::binary);
    if (!in) {
        f = Failure{2, "java.io.FileNotFoundException: " + url};
        return false;
    }
    char chunk[65536];
    while (in.read(chunk, sizeof chunk) || in.gcount() > 0) out.insert(out.end(), chunk, chunk + in.gcount());
    return true;
}

// ---------------------------------------------------------------------------------------------------------------------
// WWW: a thread per request; its callbacks take the request's number.

class Www : public JThread {
public:
    using JThread::JThread;
    jint id = 0;
    std::string url;
    std::string post;
    bool has_post = false;
    std::vector<std::pair<std::string, std::string>> headers;
};

// The headers as WWW.headerCallback(Map) joins them: "Name: value\r\n" each, the status line as "Status: ...".
std::string header_text(const std::string& status_line, const std::vector<std::pair<std::string, std::string>>& headers) {
    std::string out = "Status: " + status_line + "\r\n";
    for (auto& [k, v] : headers) out += k + ": " + v + "\r\n";
    return out;
}

void www_run(jvm::Env& e, Www& w) {
    Class& c = *jvm::find_class("com/unity3d/player/WWW");
    auto error = [&](const std::string& text) { e.call_static(c, "errorCallback", "(ILjava/lang/String;)V", {Value::I(w.id), Value(jvm::string(text))}); };
    std::string url = w.url;
    // A local URL: its length as WWW's single header ("\n\r" as its headerCallback(String, String) writes it), then the
    // contents in pieces of up to 32 KB, then done.
    if (is_local(url)) {
        std::vector<std::uint8_t> data;
        Failure f;
        if (!read_local(url, data, f)) return error(f.text);
        std::string header = "content-length: " + std::to_string(data.size()) + "\n\r";
        if (e.call_static(c, "headerCallback", "(ILjava/lang/String;)Z", {Value::I(w.id), Value(jvm::string(header))}).z()) return error(url + " aborted");
        std::size_t step = data.empty() ? 32768 : std::min<std::size_t>(data.size(), 32768);
        Ref<jvm::Array> piece = jvm::new_array(jvm::array_class(jvm::primitive_class('B')), static_cast<jsize>(step));
        for (std::size_t at = 0; at < data.size(); at += step) {
            std::size_t n = std::min(step, data.size() - at);
            std::memcpy(piece->bytes.data(), data.data() + at, n);
            if (e.call_static(c, "readCallback", "(I[BI)Z", {Value::I(w.id), Value(piece), Value::I(static_cast<jint>(n))}).z()) return error(url + " aborted");
            e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(static_cast<float>(at + n) / static_cast<float>(data.size())), Value::D(0.0), Value::I(static_cast<jint>(data.size()))});
        }
        e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(1.0f), Value::D(0.0), Value::I(static_cast<jint>(data.size()))});
        e.call_static(c, "doneCallback", "(I)V", {Value::I(w.id)});
        return;
    }
    // Redirects (301 and 302) are followed, five at most, as WWW.runSafe does.
    for (int hop = 0;; ++hop) {
        if (hop >= 5) return error("Too many redirects");
        Url u;
        Failure f;
        Http http;
        int status = 0;
        std::string reason;
        std::vector<std::pair<std::string, std::string>> headers;
        if (!parse_url(url, u, f) || !http.send(w.has_post ? "POST" : "GET", u, w.headers, w.post, 0, f) || !http.head(status, reason, headers, f)) return error(f.text);
        if (status == 301 || status == 302) {
            auto loc = std::find_if(headers.begin(), headers.end(), [](auto& h) { return strcasecmp(h.first.c_str(), "Location") == 0; });
            if (loc != headers.end()) {
                url = loc->second;
                continue;
            }
        }
        // The headers; a true answer means the game aborted the request.
        if (e.call_static(c, "headerCallback", "(ILjava/lang/String;)Z", {Value::I(w.id), Value(jvm::string(header_text(http.status_line(), headers)))}).z())
            return error(url + " aborted");
        // The body in pieces of 1428 bytes, the size WWW reads from a network connection.
        long long total = http.content_length() > 0 ? http.content_length() : 0;
        Ref<jvm::Array> piece = jvm::new_array(jvm::array_class(jvm::primitive_class('B')), 1428);
        long long got = 0;
        for (;;) {
            long n = http.read(reinterpret_cast<char*>(piece->bytes.data()), piece->bytes.size(), f);
            if (n < 0) return error(f.text);
            if (n == 0) break;
            if (e.call_static(c, "readCallback", "(I[BI)Z", {Value::I(w.id), Value(piece), Value::I(static_cast<jint>(n))}).z()) return error(url + " aborted");
            got += n;
            if (status < 400) {
                float done = total > 0 ? static_cast<float>(got) / static_cast<float>(total) : 0.0f;
                e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(done), Value::D(0.0), Value::I(static_cast<jint>(total))});
            }
        }
        // An HTTP error's body was read as above; the error itself is "<code>: <message>".
        if (status >= 400) error(std::to_string(status) + ": " + reason);
        e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(1.0f), Value::D(0.0), Value::I(static_cast<jint>(got))});
        e.call_static(c, "doneCallback", "(I)V", {Value::I(w.id)});
        return;
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// UnityWebRequest: run() on the game's own thread; its callbacks take the request's native pointer.

class WebRequest : public Object {
public:
    using Object::Object;
    jlong ptr = 0;
    std::string method, url;
    std::vector<std::pair<std::string, std::string>> headers;
    jint timeout_ms = 0;
};

void uwr_run(jvm::Env& e, WebRequest& r) {
    Class& c = *jvm::find_class("com/unity3d/player/UnityWebRequest");
    const Value p = Value::J(r.ptr);
    auto error = [&](const Failure& f) { e.call_static(c, "errorCallback", "(JILjava/lang/String;)V", {p, Value::I(f.code), Value(jvm::string(f.text))}); };
    // The body to send: uploadCallback(null) says whether there is one, then fills a 128 KB buffer at a time.
    Ref<jvm::Buffer> buffer = jvm::new_buffer(131072);
    std::string body;
    if (e.call_static(c, "uploadCallback", "(JLjava/nio/ByteBuffer;)I", {p, Value()}).i() > 0) {
        for (;;) {
            jint n = e.call_static(c, "uploadCallback", "(JLjava/nio/ByteBuffer;)I", {p, Value(buffer)}).i();
            if (n <= 0) break;
            body.append(static_cast<const char*>(buffer->address), static_cast<std::size_t>(n));
        }
    }
    // jar: is refused, as UnityWebRequest's Java refuses it; file: is read whole.
    if (strncasecmp(r.url.c_str(), "jar:", 4) == 0) return error(Failure{4, "A URL Connection to a Java ARchive (JAR) file or an entry in a JAR file is not supported"});
    if (is_local(r.url)) {
        std::vector<std::uint8_t> data;
        Failure lf;
        if (!read_local(r.url, data, lf)) return error(lf);
        e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string("content-length")), Value(jvm::string(std::to_string(data.size())))});
        e.call_static(c, "contentLengthCallback", "(JI)V", {p, Value::I(static_cast<jint>(data.size()))});
        for (std::size_t at = 0; at < data.size();) {
            std::size_t n = std::min<std::size_t>(data.size() - at, static_cast<std::size_t>(buffer->capacity));
            std::memcpy(buffer->address, data.data() + at, n);
            at += n;
            if (!e.call_static(c, "downloadCallback", "(JLjava/nio/ByteBuffer;I)Z", {p, Value(buffer), Value::I(static_cast<jint>(n))}).z()) break;
        }
        return;
    }
    Url u;
    Failure f;
    Http http;
    int status = 0;
    std::string reason;
    std::vector<std::pair<std::string, std::string>> headers;
    if (!parse_url(r.url, u, f) || !http.send(r.method, u, r.headers, body, r.timeout_ms, f) || !http.head(status, reason, headers, f)) return error(f);
    e.call_static(c, "responseCodeCallback", "(JI)V", {p, Value::I(status)});
    e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string("Status")), Value(jvm::string(http.status_line()))});
    for (auto& [k, v] : headers) e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string(k)), Value(jvm::string(v))});
    e.call_static(c, "contentLengthCallback", "(JI)V", {p, Value::I(static_cast<jint>(http.content_length()))});
    e.call_static(c, "responseCodeCallback", "(JI)V", {p, Value::I(status)});
    // The body into the buffer, a read at a time; false from the game stops it.
    for (;;) {
        long n = http.read(static_cast<char*>(buffer->address), static_cast<std::size_t>(buffer->capacity), f);
        if (n < 0) return error(f);
        if (n == 0) break;
        if (!e.call_static(c, "downloadCallback", "(JLjava/nio/ByteBuffer;I)Z", {p, Value(buffer), Value::I(static_cast<jint>(n))}).z()) break;
    }
}

}  // namespace

bool http_request(const std::string& method, const std::string& url, const std::vector<std::pair<std::string, std::string>>& headers,
                  const std::string& body, int timeout_ms, int& status, std::string& reply, std::string& error) {
    Url u;
    Failure f;
    Http http;
    std::string reason;
    std::vector<std::pair<std::string, std::string>> got;
    if (!parse_url(url, u, f) || !http.send(method, u, headers, body, timeout_ms, f) || !http.head(status, reason, got, f)) {
        error = f.text;
        return false;
    }
    char chunk[16384];
    for (;;) {
        long n = http.read(chunk, sizeof chunk, f);
        if (n < 0) {
            error = f.text;
            return false;
        }
        if (n == 0) return true;
        reply.append(chunk, static_cast<std::size_t>(n));
    }
}

void define_web() {
    Class& w = jvm::define("com/unity3d/player/WWW", "java/lang/Thread");
    w.make = [](Class& k) -> Object* { return new Www(&k); };
    w.method("<init>", "(ILjava/lang/String;[BLjava/util/Map;)V", [](Call& c) {
        Www& self = c.self_as<Www>();
        self.id = c.i(0);
        self.url = c.str(1);
        if (auto* data = c.as<jvm::Array>(2)) {
            self.has_post = true;
            self.post.assign(reinterpret_cast<const char*>(data->bytes.data()), data->bytes.size());
        }
        self.headers = string_pairs(c.l(3));
        self.name = "WWW";
        return Value();
    });
    w.method("run", "()V", [](Call& c) {
        www_run(c.env, c.self_as<Www>());
        return Value();
    });
    Class& r = jvm::define("com/unity3d/player/UnityWebRequest");
    r.interfaces.push_back(jvm::find_class("java/lang/Runnable"));
    r.make = [](Class& k) -> Object* { return new WebRequest(&k); };
    r.method("<init>", "(JLjava/lang/String;Ljava/util/Map;Ljava/lang/String;I)V", [](Call& c) {
        WebRequest& self = c.self_as<WebRequest>();
        self.ptr = c.j(0);
        self.method = c.str(1);
        self.headers = string_pairs(c.l(2));
        self.url = c.str(3);
        self.timeout_ms = c.i(4);
        return Value();
    });
    r.method("run", "()V", [](Call& c) {
        uwr_run(c.env, c.self_as<WebRequest>());
        return Value();
    });
}

}  // namespace player
