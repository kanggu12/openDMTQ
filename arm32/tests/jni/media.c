// The 32-bit side of the graphics and audio checks: EGL and OpenGL ES on a pbuffer, and an
// OpenSL ES buffer queue player whose callbacks run on the host's audio thread.
#define EGL_EGLEXT_PROTOTYPES 1
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES3/gl3.h>
#include <SLES/OpenSLES.h>
#include <SLES/OpenSLES_Android.h>
#include <jni.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static GLuint shader(GLenum type, const char** parts, int n) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, n, parts, NULL);  // several strings: the bridge converts the array
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    return ok ? s : 0;
}

static int pixel_is(int r, int g, int b) {
    unsigned char px[4] = {0};
    glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    return px[0] == r && px[1] == g && px[2] == b;
}

// OpenGL ES 3 checks of mapped buffers and fences, bits 512 to 4096.
static int es3_checks(EGLDisplay d) {
    int ok = 0;
    GLuint b[3];
    glGenBuffers(3, b);
    // A write-only map without an invalidate flag keeps the bytes the guest does not write.
    unsigned char init[64];
    for (int i = 0; i < 64; i++) init[i] = (unsigned char)i;
    glBindBuffer(GL_ARRAY_BUFFER, b[0]);
    glBufferData(GL_ARRAY_BUFFER, sizeof init, init, GL_DYNAMIC_DRAW);
    unsigned char* w = glMapBufferRange(GL_ARRAY_BUFFER, 0, sizeof init, GL_MAP_WRITE_BIT);
    if (w) w[10] = 0xee;
    glUnmapBuffer(GL_ARRAY_BUFFER);
    unsigned char* r = glMapBufferRange(GL_ARRAY_BUFFER, 0, sizeof init, GL_MAP_READ_BIT);
    if (w && r && r[10] == 0xee && r[0] == 0 && r[11] == 11 && r[63] == 63) ok |= 512;
    glUnmapBuffer(GL_ARRAY_BUFFER);
    // Two buffers mapped at once through one target: each keeps what was written to it.
    for (int k = 1; k < 3; k++) {
        glBindBuffer(GL_COPY_WRITE_BUFFER, b[k]);
        glBufferData(GL_COPY_WRITE_BUFFER, 32, NULL, GL_DYNAMIC_DRAW);
    }
    glBindBuffer(GL_COPY_WRITE_BUFFER, b[1]);
    unsigned char* m1 = glMapBufferRange(GL_COPY_WRITE_BUFFER, 0, 32, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
    glBindBuffer(GL_COPY_WRITE_BUFFER, b[2]);
    unsigned char* m2 = glMapBufferRange(GL_COPY_WRITE_BUFFER, 0, 32, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
    if (m1) memset(m1, 0x11, 32);
    if (m2) memset(m2, 0x22, 32);
    glUnmapBuffer(GL_COPY_WRITE_BUFFER);  // b[2], bound last
    glBindBuffer(GL_COPY_WRITE_BUFFER, b[1]);
    glUnmapBuffer(GL_COPY_WRITE_BUFFER);  // b[1]
    int both = m1 && m2;
    for (int k = 1; k < 3; k++) {
        glBindBuffer(GL_COPY_READ_BUFFER, b[k]);
        unsigned char* rk = glMapBufferRange(GL_COPY_READ_BUFFER, 0, 32, GL_MAP_READ_BIT);
        unsigned char want = k == 1 ? 0x11 : 0x22;
        both = both && rk && rk[0] == want && rk[31] == want;
        glUnmapBuffer(GL_COPY_READ_BUFFER);
    }
    if (both) ok |= 1024;
    // The copy behind a mapping is kept for the next one: the same address comes back although
    // other memory was mapped meanwhile (a fresh guest mapping per map cost system calls per page).
    glBindBuffer(GL_ARRAY_BUFFER, b[0]);
    void* p1 = glMapBufferRange(GL_ARRAY_BUFFER, 0, sizeof init, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
    glUnmapBuffer(GL_ARRAY_BUFFER);
    void* other = mmap(NULL, 1 << 20, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    void* p2 = glMapBufferRange(GL_ARRAY_BUFFER, 0, sizeof init, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
    glUnmapBuffer(GL_ARRAY_BUFFER);
    if (other != MAP_FAILED) munmap(other, 1 << 20);
    if (p1 && p1 == p2) ok |= 2048;
    // Waits for the GPU run detached from the guest, so a collector's stop-the-world does not wait
    // with them; they still return what the driver says.
    GLsync f = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    GLenum gw = f ? glClientWaitSync(f, GL_SYNC_FLUSH_COMMANDS_BIT, 1000000000ull) : 0;
    if (f) glDeleteSync(f);
    EGLSyncKHR es = eglCreateSyncKHR(d, EGL_SYNC_FENCE_KHR, NULL);
    EGLint ew = es != EGL_NO_SYNC_KHR ? eglClientWaitSyncKHR(d, es, EGL_SYNC_FLUSH_COMMANDS_BIT_KHR, 1000000000ull) : EGL_CONDITION_SATISFIED_KHR;
    if (es != EGL_NO_SYNC_KHR) eglDestroySyncKHR(d, es);
    if ((gw == GL_ALREADY_SIGNALED || gw == GL_CONDITION_SATISFIED) && ew == EGL_CONDITION_SATISFIED_KHR) ok |= 4096;
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glDeleteBuffers(3, b);
    return ok;
}

// Bit per check; 8191 when all pass.
jint media_gl(JNIEnv* e, jclass c) {
    (void)e, (void)c;
    int ok = 0;
    EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    eglInitialize(d, NULL, NULL);
    EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8,
                      EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    EGLConfig cfg;
    EGLint n = 0;
    eglChooseConfig(d, attrs, &cfg, 1, &n);
    EGLint pb[] = {EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE};
    EGLSurface s = eglCreatePbufferSurface(d, cfg, pb);
    EGLint ctx_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext ctx = eglCreateContext(d, cfg, EGL_NO_CONTEXT, ctx_attrs);
    if (!ctx) {
        ctx_attrs[1] = 2;
        ctx = eglCreateContext(d, cfg, EGL_NO_CONTEXT, ctx_attrs);
    }
    if (n == 1 && s && ctx && eglMakeCurrent(d, s, s, ctx)) ok |= 1;
    else return ok;
    const char* version = (const char*)glGetString(GL_VERSION);
    if (version && version[0]) ok |= 2;
    glClearColor(1, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    if (pixel_is(255, 0, 0)) ok |= 4;
    const char* vs[] = {"attribute vec2 p;\n", "void main() { gl_Position = vec4(p, 0.0, 1.0); }\n"};
    const char* fs[] = {"precision mediump float;\n", "void main() { gl_FragColor = vec4(0.0, 1.0, 0.0, 1.0); }\n"};
    GLuint prog = glCreateProgram();
    glAttachShader(prog, shader(GL_VERTEX_SHADER, vs, 2));
    glAttachShader(prog, shader(GL_FRAGMENT_SHADER, fs, 2));
    glBindAttribLocation(prog, 0, "p");
    glLinkProgram(prog);
    glUseProgram(prog);
    float tri[] = {-1, -1, 3, -1, -1, 3};
    GLuint vbo;
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof tri, tri, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);  // an offset into the buffer
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    if (pixel_is(0, 255, 0)) ok |= 8;
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glClearColor(0, 0, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, tri);  // a real pointer: client memory
    glDrawArrays(GL_TRIANGLES, 0, 3);
    if (pixel_is(0, 255, 0)) ok |= 16;
    if (ctx_attrs[1] == 3) {
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof tri, NULL, GL_DYNAMIC_DRAW);
        float* m = glMapBufferRange(GL_ARRAY_BUFFER, 0, sizeof tri, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
        if (m) memcpy(m, tri, sizeof tri);
        glUnmapBuffer(GL_ARRAY_BUFFER);
        glClear(GL_COLOR_BUFFER_BIT);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        if (m && pixel_is(0, 255, 0)) ok |= 32;
    } else {
        ok |= 32;
    }
    void (*clear)(GLbitfield) = (void (*)(GLbitfield))eglGetProcAddress("glClear");
    if (clear) ok |= 64;
    if (glGetError() == GL_NO_ERROR) ok |= 128;
    // Handles are per kind: a sync call handed the display's handle must leave the display alone.
    // (Android's display is 1, and so is the first fence of some drivers: with one table keyed by
    // value they shared a handle, and deleting that fence lost the display.)
    glDeleteSync((GLsync)d);
    if (eglQueryString(d, EGL_VENDOR) != NULL) ok |= 256;
    glGetError();  // what the stray delete left
    ok |= ctx_attrs[1] == 3 ? es3_checks(d) : 512 | 1024 | 2048 | 4096;
    eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(d, ctx);
    eglDestroySurface(d, s);
    return ok;
}

static volatile int callbacks = 0;
static short buffers[2][480];  // silence

static void on_buffer(SLAndroidSimpleBufferQueueItf q, void* context) {
    (void)context;
    callbacks++;
    (*q)->Enqueue(q, buffers[callbacks & 1], sizeof buffers[0]);
}

// Number of buffer queue callbacks received while playing silence, or a negative step number.
jint media_audio(JNIEnv* e, jclass c, jint want) {
    (void)e, (void)c;
    SLObjectItf engine, mix, player;
    SLEngineItf eng;
    SLPlayItf play;
    SLAndroidSimpleBufferQueueItf q;
    callbacks = 0;
    if (slCreateEngine(&engine, 0, NULL, 0, NULL, NULL) != SL_RESULT_SUCCESS) return -1;
    if ((*engine)->Realize(engine, SL_BOOLEAN_FALSE) != SL_RESULT_SUCCESS) return -2;
    if ((*engine)->GetInterface(engine, SL_IID_ENGINE, &eng) != SL_RESULT_SUCCESS) return -3;
    if ((*eng)->CreateOutputMix(eng, &mix, 0, NULL, NULL) != SL_RESULT_SUCCESS) return -4;
    (*mix)->Realize(mix, SL_BOOLEAN_FALSE);
    SLDataLocator_AndroidSimpleBufferQueue loc = {SL_DATALOCATOR_ANDROIDSIMPLEBUFFERQUEUE, 2};
    SLDataFormat_PCM fmt = {SL_DATAFORMAT_PCM, 1, SL_SAMPLINGRATE_48, SL_PCMSAMPLEFORMAT_FIXED_16, SL_PCMSAMPLEFORMAT_FIXED_16,
                            SL_SPEAKER_FRONT_CENTER, SL_BYTEORDER_LITTLEENDIAN};
    SLDataSource src = {&loc, &fmt};
    SLDataLocator_OutputMix out = {SL_DATALOCATOR_OUTPUTMIX, mix};
    SLDataSink snk = {&out, NULL};
    const SLInterfaceID ids[] = {SL_IID_ANDROIDSIMPLEBUFFERQUEUE};
    const SLboolean required[] = {SL_BOOLEAN_TRUE};
    if ((*eng)->CreateAudioPlayer(eng, &player, &src, &snk, 1, ids, required) != SL_RESULT_SUCCESS) return -5;
    if ((*player)->Realize(player, SL_BOOLEAN_FALSE) != SL_RESULT_SUCCESS) return -6;
    if ((*player)->GetInterface(player, SL_IID_PLAY, &play) != SL_RESULT_SUCCESS) return -7;
    if ((*player)->GetInterface(player, SL_IID_ANDROIDSIMPLEBUFFERQUEUE, &q) != SL_RESULT_SUCCESS) return -8;
    (*q)->RegisterCallback(q, on_buffer, NULL);
    (*q)->Enqueue(q, buffers[0], sizeof buffers[0]);
    (*play)->SetPlayState(play, SL_PLAYSTATE_PLAYING);
    for (int i = 0; i < 300 && callbacks < want; i++) usleep(10000);
    (*play)->SetPlayState(play, SL_PLAYSTATE_STOPPED);
    (*player)->Destroy(player);
    (*mix)->Destroy(mix);
    (*engine)->Destroy(engine);
    return callbacks;
}
