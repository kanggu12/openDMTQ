// Helpers shared by the system API bridges, and the OpenGL ES functions that need more than
// argument conversion: strings returned to the guest, mapped buffers, sync objects, arrays of
// string pointers, debug callbacks and EGL images.
#include "gl_bridge.h"

#include <algorithm>
#include <dlfcn.h>
#include <set>

#define GL_GLEXT_PROTOTYPES 1
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>

namespace arm32 {

// ---------------------------------------------------------------------------------------------
// Shared helpers.

void* gl_ptr(std::uint32_t v) {
    if (!v) return nullptr;
    if (v >= kLowestGuestPointer) return gmem().host(v);
    return reinterpret_cast<void*>(static_cast<std::uintptr_t>(v));
}

gaddr guest_addr(const void* host) {
    auto* p = static_cast<const std::uint8_t*>(host);
    if (p < gmem().base() || p >= gmem().base() + (std::uint64_t{1} << 32)) return 0;
    return static_cast<gaddr>(p - gmem().base());
}

namespace {
std::mutex g_arena_lock;
gaddr g_arena_next = 0, g_arena_end = 0;
constexpr std::uint32_t kArenaChunk = 1 << 20;
}  // namespace

gaddr arena_alloc(std::size_t size) {
    std::lock_guard<std::mutex> l(g_arena_lock);
    size = (size + 7) & ~std::size_t{7};
    if (g_arena_next + size > g_arena_end) {
        std::uint32_t chunk = static_cast<std::uint32_t>(std::max<std::size_t>(kArenaChunk, size));
        std::int64_t at = gmem().map(0, chunk, kProtRead | kProtWrite, false, "[arm32 bridge]");
        if (at < 0) return 0;
        g_arena_next = static_cast<gaddr>(at);
        g_arena_end = g_arena_next + chunk;
    }
    gaddr p = g_arena_next;
    g_arena_next += static_cast<gaddr>(size);
    return p;
}

gaddr arena_strdup(const char* s) {
    if (!s) return 0;
    std::size_t n = std::strlen(s) + 1;
    gaddr g = arena_alloc(n);
    if (g) std::memcpy(gmem().host(g), s, n);
    return g;
}

std::uint32_t HandleTable::put(HandleKind kind, const void* p) {
    if (!p) return 0;
    std::lock_guard<std::mutex> l(lock_);
    auto& ids = ids_[static_cast<std::size_t>(kind)];
    auto it = ids.find(p);
    if (it != ids.end()) return 0x70000000 | it->second;
    std::uint32_t i;
    if (!free_.empty()) {
        i = free_.back();
        free_.pop_back();
        entries_[i] = Entry{p, kind};
    } else {
        i = static_cast<std::uint32_t>(entries_.size());
        entries_.push_back(Entry{p, kind});
    }
    ids[p] = i;
    return 0x70000000 | i;
}

void* HandleTable::get(HandleKind kind, std::uint32_t h) {
    if (!h) return nullptr;
    std::lock_guard<std::mutex> l(lock_);
    std::uint32_t i = h & 0x0fffffff;
    if ((h & 0xf0000000) != 0x70000000 || i >= entries_.size() || !entries_[i].p ||
        (kind != HandleKind::kAny && entries_[i].kind != kind)) {
        log("arm32: bad handle %#x", h);
        return nullptr;
    }
    return const_cast<void*>(entries_[i].p);
}

void HandleTable::drop(HandleKind kind, std::uint32_t h) {
    std::lock_guard<std::mutex> l(lock_);
    std::uint32_t i = h & 0x0fffffff;
    // Only a live handle of this kind: a stale or foreign one (a fence call handed the display)
    // leaves the table alone.
    if ((h & 0xf0000000) != 0x70000000 || i >= entries_.size() || !entries_[i].p || entries_[i].kind != kind) return;
    ids_[static_cast<std::size_t>(kind)].erase(entries_[i].p);
    entries_[i] = Entry{nullptr, HandleKind::kAny};
    free_.push_back(i);
}

HandleTable& handles() {
    static HandleTable table;
    return table;
}

void* gl_proc(const char* name) {
    static void* gles = dlopen("libGLESv3.so", RTLD_NOW | RTLD_LOCAL);
    static void* egl = dlopen("libEGL.so", RTLD_NOW | RTLD_LOCAL);
    static auto get_proc = egl ? reinterpret_cast<void* (*)(const char*)>(dlsym(egl, "eglGetProcAddress")) : nullptr;
    void* f = gles ? dlsym(gles, name) : nullptr;
    if (!f && get_proc) f = get_proc(name);
    return f;
}

std::uint64_t gl_missing(const char* name) {
    static std::mutex lock;
    static std::set<std::string> logged;
    std::lock_guard<std::mutex> l(lock);
    if (logged.insert(name).second) log("arm32: gl: %s is not available on this device", name);
    return 0;
}

// ---------------------------------------------------------------------------------------------
// Strings: copied into the arena once per host string.

namespace {

gaddr cached_string(const GLubyte* s) {
    static std::mutex lock;
    static std::unordered_map<const GLubyte*, gaddr> copies;
    if (!s) return 0;
    std::lock_guard<std::mutex> l(lock);
    auto it = copies.find(s);
    if (it != copies.end()) return it->second;
    gaddr g = arena_strdup(reinterpret_cast<const char*>(s));
    copies[s] = g;
    return g;
}

#define ARM32_FN(type, name) static auto fn = reinterpret_cast<type>(gl_proc(#name))

}  // namespace

std::uint64_t gl_special_glGetString(Thread& t) {
    ARM32_FN(const GLubyte* (*)(GLenum), glGetString);
    Words w{t};
    return fn ? cached_string(fn(static_cast<GLenum>(w.u32()))) : 0;
}

std::uint64_t gl_special_glGetStringi(Thread& t) {
    ARM32_FN(const GLubyte* (*)(GLenum, GLuint), glGetStringi);
    Words w{t};
    auto name = static_cast<GLenum>(w.u32());
    auto index = static_cast<GLuint>(w.u32());
    return fn ? cached_string(fn(name, index)) : 0;
}

// ---------------------------------------------------------------------------------------------
// Mapped buffers. The driver's mapping is not guest memory, so the guest gets a copy, written
// back on unmap (or per range with FLUSH_EXPLICIT). The copy starts out as the buffer's contents
// unless the guest gave those up (an INVALIDATE bit): GL keeps the bytes a write-only map does
// not write, and writing back a copy that started empty put zeros there. Mappings belong to
// buffers, not to targets: two buffers can be mapped through one target at once (bound one
// after the other), so a mapping is found by the name of its buffer.

namespace {

// Guest memory for a copy.
struct Block {
    gaddr at;
    std::uint32_t size;
};

struct Mapping {
    GLenum target;     // the target it was mapped through
    GLuint name;       // its buffer
    void* host;        // the driver's mapping
    Block block;       // the guest's copy
    std::uint32_t length;
    GLbitfield access;
};

// A thread's mappings, and the copies kept for its next ones: a fresh guest mapping per map
// (several a frame for dynamic geometry) cost an mmap and an munmap with their system calls and
// page faults on the render thread each time.
struct Maps {
    std::vector<Mapping> active;
    std::vector<Block> spare;
    std::size_t spare_bytes = 0;
    ~Maps() {
        // The thread ends: its copies go back to the address space (no guest code needed).
        for (const Mapping& m : active) gmem().unmap(m.block.at, m.block.size);
        for (const Block& b : spare) gmem().unmap(b.at, b.size);
    }
};
// GL contexts are current per thread, and so are their mappings.
thread_local Maps t_maps;
// Copies are made in steps of this size, so that one serves later maps of about the same size.
constexpr std::uint32_t kBlockStep = 64 << 10;
// Spare copies a thread keeps beyond this many bytes go back, largest first.
constexpr std::size_t kSpareBytes = 8 << 20;

Block take_block(std::uint32_t length) {
    auto& spare = t_maps.spare;
    // The smallest spare copy that is big enough; of equal ones the last given back, whose pages
    // are the most likely to be in the cache still.
    auto best = spare.rend();
    for (auto it = spare.rbegin(); it != spare.rend(); ++it) {
        if (it->size >= length && (best == spare.rend() || it->size < best->size)) best = it;
    }
    if (best != spare.rend()) {
        Block b = *best;
        t_maps.spare_bytes -= b.size;
        spare.erase(std::next(best).base());
        return b;
    }
    std::uint64_t size = (std::uint64_t{length} + kBlockStep - 1) / kBlockStep * kBlockStep;
    std::int64_t at = gmem().map(0, static_cast<std::uint32_t>(size), kProtRead | kProtWrite, false, "[gl mapped buffer]");
    if (at < 0) return Block{0, 0};
    return Block{static_cast<gaddr>(at), static_cast<std::uint32_t>(size)};
}

void give_block(Block b) {
    auto& spare = t_maps.spare;
    spare.push_back(b);
    t_maps.spare_bytes += b.size;
    while (t_maps.spare_bytes > kSpareBytes && !spare.empty()) {
        auto largest = std::max_element(spare.begin(), spare.end(), [](const Block& x, const Block& y) { return x.size < y.size; });
        t_maps.spare_bytes -= largest->size;
        gmem().unmap(largest->at, largest->size);
        spare.erase(largest);
    }
}

// The buffer bound to target, by name: 0 for none, or for a target not known here.
GLuint bound_buffer(GLenum target) {
    GLenum binding = 0;
    switch (target) {
    case GL_ARRAY_BUFFER: binding = GL_ARRAY_BUFFER_BINDING; break;
    case GL_ELEMENT_ARRAY_BUFFER: binding = GL_ELEMENT_ARRAY_BUFFER_BINDING; break;
    case GL_PIXEL_PACK_BUFFER: binding = GL_PIXEL_PACK_BUFFER_BINDING; break;
    case GL_PIXEL_UNPACK_BUFFER: binding = GL_PIXEL_UNPACK_BUFFER_BINDING; break;
    case GL_COPY_READ_BUFFER: binding = GL_COPY_READ_BUFFER_BINDING; break;
    case GL_COPY_WRITE_BUFFER: binding = GL_COPY_WRITE_BUFFER_BINDING; break;
    case GL_TRANSFORM_FEEDBACK_BUFFER: binding = GL_TRANSFORM_FEEDBACK_BUFFER_BINDING; break;
    case GL_UNIFORM_BUFFER: binding = GL_UNIFORM_BUFFER_BINDING; break;
    case GL_ATOMIC_COUNTER_BUFFER: binding = GL_ATOMIC_COUNTER_BUFFER_BINDING; break;
    case GL_DISPATCH_INDIRECT_BUFFER: binding = GL_DISPATCH_INDIRECT_BUFFER_BINDING; break;
    case GL_DRAW_INDIRECT_BUFFER: binding = GL_DRAW_INDIRECT_BUFFER_BINDING; break;
    case GL_SHADER_STORAGE_BUFFER: binding = GL_SHADER_STORAGE_BUFFER_BINDING; break;
    default: return 0;
    }
    static auto get = reinterpret_cast<void (*)(GLenum, GLint*)>(gl_proc("glGetIntegerv"));
    GLint v = 0;
    if (get) get(binding, &v);
    return static_cast<GLuint>(v);
}

// The mapping an unmap, a flush or a pointer query through target is about: the one of the
// buffer bound there. A thread's only mapping, made through that target, needs no question to
// the driver (the usual map, write, unmap).
std::vector<Mapping>::iterator find_mapping(GLenum target) {
    auto& active = t_maps.active;
    if (active.size() == 1 && active.front().target == target) return active.begin();
    if (active.empty()) return active.end();
    GLuint name = bound_buffer(target);
    return std::find_if(active.begin(), active.end(), [name](const Mapping& m) { return m.name == name; });
}

// The guest's copy is let go without writing it back (an unmap that failed, a deleted buffer).
void forget(std::vector<Mapping>::iterator it) {
    give_block(it->block);
    t_maps.active.erase(it);
}

// Whether a map must start the copy from the buffer's contents: unless an INVALIDATE bit said
// the old contents can go, the guest may read them (READ) or leave them (a write-only map keeps
// the bytes it does not write).
bool needs_contents(GLbitfield access) {
    return !(access & (GL_MAP_INVALIDATE_RANGE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT));
}

// The access asked of the driver: READ as well where the copy must be filled and GL allows it
// (not with UNSYNCHRONIZED), so that reading the mapping is defined.
GLbitfield host_access(GLbitfield access) {
    if (needs_contents(access) && !(access & (GL_MAP_READ_BIT | GL_MAP_UNSYNCHRONIZED_BIT))) access |= GL_MAP_READ_BIT;
    return access;
}

std::uint64_t map_range(GLenum target, GLsizeiptr length, GLbitfield access, void* host) {
    if (!host || length <= 0) return 0;
    GLuint name = bound_buffer(target);
    // The driver mapped this buffer, so a mapping of it still listed here is stale: the buffer
    // was deleted or unmapped by a call that did not come this way.
    auto& active = t_maps.active;
    for (auto it = active.begin(); it != active.end();) {
        if (name && it->name == name) {
            give_block(it->block);
            it = active.erase(it);
        } else {
            ++it;
        }
    }
    Block b = take_block(static_cast<std::uint32_t>(length));
    if (!b.at) return 0;
    if (needs_contents(access)) std::memcpy(gmem().host(b.at), host, static_cast<std::size_t>(length));
    active.push_back(Mapping{target, name, host, b, static_cast<std::uint32_t>(length), access});
    return b.at;
}

std::uint64_t unmap(GLenum target, GLboolean (*fn)(GLenum)) {
    auto it = find_mapping(target);
    if (it != t_maps.active.end()) {
        // With FLUSH_EXPLICIT only the flushed ranges count, and those are copied already.
        if ((it->access & GL_MAP_WRITE_BIT) && !(it->access & GL_MAP_FLUSH_EXPLICIT_BIT)) {
            std::memcpy(it->host, gmem().host(it->block.at), it->length);
        }
        forget(it);
    }
    return fn ? fn(target) : 0;
}

std::uint64_t flush_range(GLenum target, GLintptr offset, GLsizeiptr length, void (*fn)(GLenum, GLintptr, GLsizeiptr)) {
    auto it = find_mapping(target);
    if (it != t_maps.active.end() && offset >= 0 && length >= 0 && static_cast<std::uint64_t>(offset + length) <= it->length) {
        std::memcpy(static_cast<std::uint8_t*>(it->host) + offset, gmem().host(it->block.at + static_cast<gaddr>(offset)),
                    static_cast<std::size_t>(length));
    }
    if (fn) fn(target, offset, length);
    return 0;
}

}  // namespace

std::uint64_t gl_special_glMapBufferRange(Thread& t) {
    ARM32_FN(void* (*)(GLenum, GLintptr, GLsizeiptr, GLbitfield), glMapBufferRange);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto offset = static_cast<GLintptr>(static_cast<std::int32_t>(w.u32()));
    auto length = static_cast<GLsizeiptr>(static_cast<std::int32_t>(w.u32()));
    auto access = static_cast<GLbitfield>(w.u32());
    if (!fn) return gl_missing("glMapBufferRange");
    return map_range(target, length, access, fn(target, offset, length, host_access(access)));
}

std::uint64_t gl_special_glMapBufferRangeEXT(Thread& t) {
    ARM32_FN(void* (*)(GLenum, GLintptr, GLsizeiptr, GLbitfield), glMapBufferRangeEXT);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto offset = static_cast<GLintptr>(static_cast<std::int32_t>(w.u32()));
    auto length = static_cast<GLsizeiptr>(static_cast<std::int32_t>(w.u32()));
    auto access = static_cast<GLbitfield>(w.u32());
    if (!fn) return gl_missing("glMapBufferRangeEXT");
    return map_range(target, length, access, fn(target, offset, length, host_access(access)));
}

std::uint64_t gl_special_glMapBufferOES(Thread& t) {
    ARM32_FN(void* (*)(GLenum, GLenum), glMapBufferOES);
    static auto get_param = reinterpret_cast<void (*)(GLenum, GLenum, GLint*)>(gl_proc("glGetBufferParameteriv"));
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto access = static_cast<GLenum>(w.u32());
    if (!fn || !get_param) return gl_missing("glMapBufferOES");
    GLint size = 0;
    get_param(target, GL_BUFFER_SIZE, &size);
    // The whole buffer, write-only, nothing given up: the copy starts as the buffer's contents
    // (the drivers' mappings are ordinary memory, though OES_mapbuffer does not promise reads).
    return map_range(target, size, GL_MAP_WRITE_BIT, fn(target, access));
}

std::uint64_t gl_special_glDeleteBuffers(Thread& t) {
    ARM32_FN(void (*)(GLsizei, const GLuint*), glDeleteBuffers);
    Words w{t};
    auto n = static_cast<GLsizei>(w.u32());
    auto* names = static_cast<const GLuint*>(gl_ptr(w.u32()));
    // A buffer deleted while mapped is unmapped with it: its copy goes, unwritten, so that a later
    // buffer given the same name is not taken for it.
    for (GLsizei i = 0; names && i < n; ++i) {
        if (!names[i]) continue;
        auto& active = t_maps.active;
        auto it = std::find_if(active.begin(), active.end(), [&](const Mapping& m) { return m.name == names[i]; });
        if (it != active.end()) forget(it);
    }
    if (fn) fn(n, names);
    return 0;
}

std::uint64_t gl_special_glUnmapBuffer(Thread& t) {
    ARM32_FN(GLboolean (*)(GLenum), glUnmapBuffer);
    Words w{t};
    return unmap(static_cast<GLenum>(w.u32()), fn);
}

std::uint64_t gl_special_glUnmapBufferOES(Thread& t) {
    ARM32_FN(GLboolean (*)(GLenum), glUnmapBufferOES);
    Words w{t};
    return unmap(static_cast<GLenum>(w.u32()), fn);
}

std::uint64_t gl_special_glFlushMappedBufferRange(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLintptr, GLsizeiptr), glFlushMappedBufferRange);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto offset = static_cast<GLintptr>(static_cast<std::int32_t>(w.u32()));
    auto length = static_cast<GLsizeiptr>(static_cast<std::int32_t>(w.u32()));
    return flush_range(target, offset, length, fn);
}

std::uint64_t gl_special_glFlushMappedBufferRangeEXT(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLintptr, GLsizeiptr), glFlushMappedBufferRangeEXT);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto offset = static_cast<GLintptr>(static_cast<std::int32_t>(w.u32()));
    auto length = static_cast<GLsizeiptr>(static_cast<std::int32_t>(w.u32()));
    return flush_range(target, offset, length, fn);
}

namespace {
// The mapping pointer is the guest's copy; other pointers the guest set are its own addresses.
void put_pointer(gaddr out, void* host) {
    if (!out) return;
    gaddr g = guest_addr(host);
    *gmem().ptr<std::uint32_t>(out) = g ? g : static_cast<std::uint32_t>(reinterpret_cast<std::uintptr_t>(host));
}
}  // namespace

std::uint64_t gl_special_glGetBufferPointerv(Thread& t) {
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    w.u32();  // pname: GL_BUFFER_MAP_POINTER is the only one
    gaddr out = w.u32();
    auto it = find_mapping(target);
    if (out) *gmem().ptr<std::uint32_t>(out) = it == t_maps.active.end() ? 0 : it->block.at;
    return 0;
}

std::uint64_t gl_special_glGetBufferPointervOES(Thread& t) { return gl_special_glGetBufferPointerv(t); }

std::uint64_t gl_special_glGetPointerv(Thread& t) {
    // Only debug callback pointers can be asked for in GLES, and the guest cannot set those.
    Words w{t};
    w.u32();
    gaddr out = w.u32();
    if (out) *gmem().ptr<std::uint32_t>(out) = 0;
    return 0;
}

std::uint64_t gl_special_glGetPointervKHR(Thread& t) { return gl_special_glGetPointerv(t); }

std::uint64_t gl_special_glGetVertexAttribPointerv(Thread& t) {
    ARM32_FN(void (*)(GLuint, GLenum, void**), glGetVertexAttribPointerv);
    Words w{t};
    auto index = static_cast<GLuint>(w.u32());
    auto pname = static_cast<GLenum>(w.u32());
    gaddr out = w.u32();
    void* p = nullptr;
    if (fn) fn(index, pname, &p);
    put_pointer(out, p);
    return 0;
}

// ---------------------------------------------------------------------------------------------
// Arrays of string pointers.

namespace {
std::vector<const GLchar*> string_array(gaddr array, GLsizei count) {
    std::vector<const GLchar*> v(static_cast<std::size_t>(count > 0 ? count : 0));
    for (std::size_t i = 0; i < v.size(); ++i) {
        v[i] = static_cast<const GLchar*>(gl_ptr(*gmem().ptr<std::uint32_t>(array + static_cast<gaddr>(i * 4))));
    }
    return v;
}
}  // namespace

std::uint64_t gl_special_glShaderSource(Thread& t) {
    ARM32_FN(void (*)(GLuint, GLsizei, const GLchar* const*, const GLint*), glShaderSource);
    Words w{t};
    auto shader = static_cast<GLuint>(w.u32());
    auto count = static_cast<GLsizei>(w.u32());
    auto strings = string_array(w.u32(), count);
    auto lengths = static_cast<const GLint*>(gl_ptr(w.u32()));
    if (fn) fn(shader, count, strings.data(), lengths);
    return 0;
}

std::uint64_t gl_special_glTransformFeedbackVaryings(Thread& t) {
    ARM32_FN(void (*)(GLuint, GLsizei, const GLchar* const*, GLenum), glTransformFeedbackVaryings);
    Words w{t};
    auto program = static_cast<GLuint>(w.u32());
    auto count = static_cast<GLsizei>(w.u32());
    auto names = string_array(w.u32(), count);
    auto mode = static_cast<GLenum>(w.u32());
    if (fn) fn(program, count, names.data(), mode);
    return 0;
}

std::uint64_t gl_special_glGetUniformIndices(Thread& t) {
    ARM32_FN(void (*)(GLuint, GLsizei, const GLchar* const*, GLuint*), glGetUniformIndices);
    Words w{t};
    auto program = static_cast<GLuint>(w.u32());
    auto count = static_cast<GLsizei>(w.u32());
    auto names = string_array(w.u32(), count);
    auto indices = static_cast<GLuint*>(gl_ptr(w.u32()));
    if (fn) fn(program, count, names.data(), indices);
    return 0;
}

std::uint64_t gl_special_glCreateShaderProgramv(Thread& t) {
    ARM32_FN(GLuint (*)(GLenum, GLsizei, const GLchar* const*), glCreateShaderProgramv);
    Words w{t};
    auto type = static_cast<GLenum>(w.u32());
    auto count = static_cast<GLsizei>(w.u32());
    auto strings = string_array(w.u32(), count);
    return fn ? fn(type, count, strings.data()) : gl_missing("glCreateShaderProgramv");
}

std::uint64_t gl_special_glCreateShaderProgramvEXT(Thread& t) {
    ARM32_FN(GLuint (*)(GLenum, GLsizei, const GLchar**), glCreateShaderProgramvEXT);
    Words w{t};
    auto type = static_cast<GLenum>(w.u32());
    auto count = static_cast<GLsizei>(w.u32());
    auto strings = string_array(w.u32(), count);
    return fn ? fn(type, count, const_cast<const GLchar**>(strings.data())) : gl_missing("glCreateShaderProgramvEXT");
}

// ---------------------------------------------------------------------------------------------
// Sync objects: GLsync is a pointer, so the guest gets a handle.

std::uint64_t gl_special_glFenceSync(Thread& t) {
    ARM32_FN(GLsync (*)(GLenum, GLbitfield), glFenceSync);
    Words w{t};
    auto condition = static_cast<GLenum>(w.u32());
    auto flags = static_cast<GLbitfield>(w.u32());
    return fn ? handles().put(HandleKind::kGlSync, fn(condition, flags)) : gl_missing("glFenceSync");
}

std::uint64_t gl_special_glFenceSyncAPPLE(Thread& t) { return gl_special_glFenceSync(t); }

std::uint64_t gl_special_glDeleteSync(Thread& t) {
    ARM32_FN(void (*)(GLsync), glDeleteSync);
    Words w{t};
    std::uint32_t h = w.u32();
    // A handle of another kind (or a stale one) reaches neither the driver nor the table.
    void* sync = handles().get(HandleKind::kGlSync, h);
    if (fn && sync) fn(static_cast<GLsync>(sync));
    handles().drop(HandleKind::kGlSync, h);
    return 0;
}

std::uint64_t gl_special_glDeleteSyncAPPLE(Thread& t) { return gl_special_glDeleteSync(t); }

std::uint64_t gl_special_glIsSync(Thread& t) {
    ARM32_FN(GLboolean (*)(GLsync), glIsSync);
    Words w{t};
    std::uint32_t h = w.u32();
    void* sync = handles().get(HandleKind::kGlSync, h);
    return fn && sync ? fn(static_cast<GLsync>(sync)) : 0;
}

std::uint64_t gl_special_glIsSyncAPPLE(Thread& t) { return gl_special_glIsSync(t); }

std::uint64_t gl_special_glClientWaitSync(Thread& t) {
    ARM32_FN(GLenum (*)(GLsync, GLbitfield, GLuint64), glClientWaitSync);
    Words w{t};
    auto sync = static_cast<GLsync>(handles().get(HandleKind::kGlSync, w.u32()));
    auto flags = static_cast<GLbitfield>(w.u32());
    auto timeout = static_cast<GLuint64>(w.u64());
    return fn ? fn(sync, flags, timeout) : gl_missing("glClientWaitSync");
}

std::uint64_t gl_special_glClientWaitSyncAPPLE(Thread& t) { return gl_special_glClientWaitSync(t); }

std::uint64_t gl_special_glWaitSync(Thread& t) {
    ARM32_FN(void (*)(GLsync, GLbitfield, GLuint64), glWaitSync);
    Words w{t};
    auto sync = static_cast<GLsync>(handles().get(HandleKind::kGlSync, w.u32()));
    auto flags = static_cast<GLbitfield>(w.u32());
    auto timeout = static_cast<GLuint64>(w.u64());
    if (fn) fn(sync, flags, timeout);
    return 0;
}

std::uint64_t gl_special_glWaitSyncAPPLE(Thread& t) { return gl_special_glWaitSync(t); }

std::uint64_t gl_special_glGetSynciv(Thread& t) {
    ARM32_FN(void (*)(GLsync, GLenum, GLsizei, GLsizei*, GLint*), glGetSynciv);
    Words w{t};
    auto sync = static_cast<GLsync>(handles().get(HandleKind::kGlSync, w.u32()));
    auto pname = static_cast<GLenum>(w.u32());
    auto size = static_cast<GLsizei>(w.u32());
    auto length = static_cast<GLsizei*>(gl_ptr(w.u32()));
    auto values = static_cast<GLint*>(gl_ptr(w.u32()));
    if (fn) fn(sync, pname, size, length, values);
    return 0;
}

std::uint64_t gl_special_glGetSyncivAPPLE(Thread& t) { return gl_special_glGetSynciv(t); }

// ---------------------------------------------------------------------------------------------
// Debug callbacks would be guest code called on driver threads; they are switched off.

std::uint64_t gl_special_glDebugMessageCallback(Thread& t) {
    ARM32_FN(void (*)(GLDEBUGPROC, const void*), glDebugMessageCallback);
    (void)t;
    if (fn) fn(nullptr, nullptr);
    return 0;
}

std::uint64_t gl_special_glDebugMessageCallbackKHR(Thread& t) {
    ARM32_FN(void (*)(GLDEBUGPROCKHR, const void*), glDebugMessageCallbackKHR);
    (void)t;
    if (fn) fn(nullptr, nullptr);
    return 0;
}

// ---------------------------------------------------------------------------------------------
// EGL images: handles from the EGL bridge.

std::uint64_t gl_special_glEGLImageTargetTexture2DOES(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLeglImageOES), glEGLImageTargetTexture2DOES);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    void* image = handles().get(HandleKind::kEglImage, w.u32());
    if (fn) fn(target, image);
    return 0;
}

std::uint64_t gl_special_glEGLImageTargetRenderbufferStorageOES(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLeglImageOES), glEGLImageTargetRenderbufferStorageOES);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    void* image = handles().get(HandleKind::kEglImage, w.u32());
    if (fn) fn(target, image);
    return 0;
}

}  // namespace arm32
