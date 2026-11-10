// Shared by the system API bridges (EGL, OpenGL ES, libandroid, OpenSL ES): argument reading,
// pointer translation, long-lived guest memory and 32-bit handles for host objects.
#pragma once

#include "guest.h"

#include <array>
#include <cstring>
#include <unordered_map>

namespace arm32 {

// The arguments of a stub call: r0-r3, then the caller's stack; 64-bit values at even positions.
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

inline float as_float(std::uint32_t bits) {
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}
inline std::uint32_t float_bits(float f) {
    std::uint32_t b;
    std::memcpy(&b, &f, 4);
    return b;
}

inline Memory& gmem() { return Guest::get().proc.mem; }

// A GL pointer argument as a host pointer; null stays null. mmap places no guest memory below
// kLowestGuestPointer (runtime.h), so smaller non-zero values are offsets into GL buffers and
// pass through unchanged; anything above is guest memory, mapped or not (an unmapped one faults
// in the reservation instead of reaching some host memory at that low address).
void* gl_ptr(std::uint32_t v);
// A pointer argument of the other bridges (EGL, OpenSL ES, libandroid), which take no offsets.
inline void* guest_ptr(std::uint32_t v) { return v ? gmem().host(v) : nullptr; }
// A host pointer into guest memory back as a guest address (0 if it is outside).
gaddr guest_addr(const void* host);

// Long-lived guest memory owned by the bridges: strings and tables handed to the guest.
gaddr arena_alloc(std::size_t size);
gaddr arena_strdup(const char* s);

// The kinds of host object a guest handle can stand for. Each kind has handles of its own:
// drivers hand out small integers for some objects (Android's EGL display is 1, and so is the
// first fence of a driver that numbers its fences), and with one table keyed by value a fence
// and the display shared a handle, so deleting the fence lost the display.
enum class HandleKind : std::uint8_t {
    kAny,  // get() only: whatever the handle stands for
    kEglDisplay, kEglConfig, kEglContext, kEglSurface, kEglImage, kEglSync, kGlSync,
    kWindow, kAssetManager, kAsset, kAssetDir, kConfiguration, kInputEvent, kLooper,
    kSensorManager, kSensor, kSensorQueue,
    kCount
};

// 32-bit handles for host pointers. The same pointer of a kind always gets the same handle; 0
// stands for null. get() and drop() check the handle's kind: a handle of another kind is null to
// get() and left alone by drop().
class HandleTable {
public:
    std::uint32_t put(HandleKind kind, const void* p);
    void* get(HandleKind kind, std::uint32_t h);
    void drop(HandleKind kind, std::uint32_t h);

private:
    struct Entry {
        const void* p;
        HandleKind kind;
    };
    std::mutex lock_;
    std::array<std::unordered_map<const void*, std::uint32_t>, static_cast<std::size_t>(HandleKind::kCount)> ids_;
    std::vector<Entry> entries_{Entry{nullptr, HandleKind::kAny}};
    std::vector<std::uint32_t> free_;
};
HandleTable& handles();

// Host GL entry point by name; null if the host does not have it.
void* gl_proc(const char* name);
// Logged once per name, returns 0 to the guest.
std::uint64_t gl_missing(const char* name);

// Generated: host functions for every GL function, and their names in stub order.
void gl_register();
extern const char* const kGlNames[];
extern const std::size_t kGlCount;

// Written by hand (gl_special.cpp).
#define ARM32_GL_SPECIALS(X)                                                                           \
    X(glGetString) X(glGetStringi) X(glMapBufferRange) X(glMapBufferRangeEXT) X(glMapBufferOES)          \
    X(glUnmapBuffer) X(glUnmapBufferOES) X(glFlushMappedBufferRange) X(glFlushMappedBufferRangeEXT)      \
    X(glGetBufferPointerv) X(glGetBufferPointervOES) X(glGetPointerv) X(glGetPointervKHR)               \
    X(glGetVertexAttribPointerv) X(glShaderSource) X(glTransformFeedbackVaryings) X(glGetUniformIndices) \
    X(glCreateShaderProgramv) X(glCreateShaderProgramvEXT) X(glFenceSync) X(glFenceSyncAPPLE)           \
    X(glDeleteSync) X(glDeleteSyncAPPLE) X(glIsSync) X(glIsSyncAPPLE) X(glClientWaitSync)               \
    X(glClientWaitSyncAPPLE) X(glWaitSync) X(glWaitSyncAPPLE) X(glGetSynciv) X(glGetSyncivAPPLE)        \
    X(glDebugMessageCallback) X(glDebugMessageCallbackKHR) X(glEGLImageTargetTexture2DOES)              \
    X(glEGLImageTargetRenderbufferStorageOES) X(glDeleteBuffers)                                          \
    /* offscreen.cpp: the calls that name or read framebuffer 0 */                                     \
    X(glBindFramebuffer) X(glGetIntegerv) X(glGetInteger64v) X(glGetFloatv) X(glGetBooleanv)             \
    X(glReadPixels) X(glReadnPixels) X(glReadnPixelsEXT) X(glReadnPixelsKHR) X(glCopyTexImage2D)         \
    X(glCopyTexSubImage2D) X(glCopyTexSubImage3D) X(glBlitFramebuffer) X(glInvalidateFramebuffer)        \
    X(glInvalidateSubFramebuffer) X(glDiscardFramebufferEXT) X(glDrawBuffers) X(glDrawBuffersEXT)        \
    X(glReadBuffer) X(glFramebufferTexture2D) X(glFramebufferRenderbuffer) X(glFramebufferTextureLayer)  \
    X(glFramebufferTexture) X(glFramebufferTextureEXT) X(glFramebufferTextureOES)                        \
    X(glFramebufferTexture2DMultisampleEXT) X(glFramebufferTexture3DOES) X(glFramebufferParameteri)      \
    X(glGetFramebufferAttachmentParameteriv) X(glGetFramebufferParameteriv)
#define ARM32_DECLARE(name) std::uint64_t gl_special_##name(Thread& t);
ARM32_GL_SPECIALS(ARM32_DECLARE)
#undef ARM32_DECLARE

// Registration of the hand-written bridges.
void egl_register();
void android_register();
void opensl_register();

}  // namespace arm32
