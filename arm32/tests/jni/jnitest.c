// The 32-bit side of Arm32JniTest: native methods registered from JNI_OnLoad, and a few the
// VM finds by name.
#include <dlfcn.h>
#include <jni.h>
#include <malloc.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

jint media_gl(JNIEnv* e, jclass c);
jint media_audio(JNIEnv* e, jclass c, jint want);

static JavaVM* vm;
static jclass test_class;

static jint add(JNIEnv* e, jclass c, jint a, jint b) {
    (void)e, (void)c;
    return a + b;
}

static jlong mix(JNIEnv* e, jclass c, jint a, jlong b, jint cc, jdouble d, jfloat f, jlong g, jbyte h, jshort i, jchar j, jboolean k) {
    (void)e, (void)c;
    return (jlong)a + b + cc + (jlong)d + (jlong)f + g + h + i + j + (k ? 1 : 0);
}

static jdouble average(JNIEnv* e, jclass c, jdoubleArray values) {
    (void)c;
    jsize n = (*e)->GetArrayLength(e, values);
    jdouble* v = (*e)->GetDoubleArrayElements(e, values, NULL);
    double s = 0;
    for (int i = 0; i < n; i++) s += v[i];
    (*e)->ReleaseDoubleArrayElements(e, values, v, JNI_ABORT);
    return n ? s / n : 0;
}

static jstring greet(JNIEnv* e, jclass c, jstring name) {
    (void)c;
    const char* s = (*e)->GetStringUTFChars(e, name, NULL);
    char buf[128];
    snprintf(buf, sizeof buf, "hello %s from arm32", s);
    (*e)->ReleaseStringUTFChars(e, name, s);
    return (*e)->NewStringUTF(e, buf);
}

static jint instance_sum(JNIEnv* e, jobject self, jint extra) {
    jclass cls = (*e)->GetObjectClass(e, self);
    jfieldID base = (*e)->GetFieldID(e, cls, "base", "I");
    jmethodID twice = (*e)->GetMethodID(e, cls, "twice", "(I)I");
    jint b = (*e)->GetIntField(e, self, base);
    (*e)->SetIntField(e, self, base, b + 1);
    return (*e)->CallIntMethod(e, self, twice, b + extra);
}

static jlong call_va(JNIEnv* e, jclass c, jmethodID m, ...) {
    va_list ap;
    va_start(ap, m);
    jlong r = (*e)->CallStaticLongMethodV(e, c, m, ap);
    va_end(ap);
    return r;
}

static jint callbacks(JNIEnv* e, jclass c) {
    int ok = 0;
    jmethodID mixm = (*e)->GetStaticMethodID(e, c, "staticMix", "(IJFDLjava/lang/String;)J");
    jstring s = (*e)->NewStringUTF(e, "abcd");
    jlong want = 7 + ((jlong)1 << 40) + 3 + 9 + 4;
    if ((*e)->CallStaticLongMethod(e, c, mixm, 7, (jlong)1 << 40, 3.5f, 9.75, s) == want) ok++;
    jvalue v[5];
    v[0].i = 7;
    v[1].j = (jlong)1 << 40;
    v[2].f = 3.5f;
    v[3].d = 9.75;
    v[4].l = s;
    if ((*e)->CallStaticLongMethodA(e, c, mixm, v) == want) ok++;
    if (call_va(e, c, mixm, 7, (jlong)1 << 40, 3.5f, 9.75, s) == want) ok++;
    jmethodID concat = (*e)->GetStaticMethodID(e, c, "concat", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;");
    jstring r = (jstring)(*e)->CallStaticObjectMethod(e, c, concat, s, s);
    const char* rs = (*e)->GetStringUTFChars(e, r, NULL);
    if (strcmp(rs, "abcdabcd") == 0) ok++;
    (*e)->ReleaseStringUTFChars(e, r, rs);
    return ok;
}

static jintArray reverse(JNIEnv* e, jclass c, jintArray in) {
    (void)c;
    jsize n = (*e)->GetArrayLength(e, in);
    jint* buf = malloc((size_t)n * sizeof(jint));
    (*e)->GetIntArrayRegion(e, in, 0, n, buf);
    jintArray out = (*e)->NewIntArray(e, n);
    jint* o = (*e)->GetIntArrayElements(e, out, NULL);
    for (int i = 0; i < n; i++) o[i] = buf[n - 1 - i];
    (*e)->ReleaseIntArrayElements(e, out, o, 0);
    free(buf);
    return out;
}

static void fill(JNIEnv* e, jclass c, jobject buf, jbyte value) {
    (void)c;
    unsigned char* p = (*e)->GetDirectBufferAddress(e, buf);
    memset(p, value, (size_t)(*e)->GetDirectBufferCapacity(e, buf));
}

static unsigned char guest_bytes[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};

static jobject wrap(JNIEnv* e, jclass c) {
    (void)c;
    return (*e)->NewDirectByteBuffer(e, guest_bytes, sizeof guest_bytes);
}

static void raise_exception(JNIEnv* e, jclass c, jstring message) {
    (void)c;
    jclass ex = (*e)->FindClass(e, "java/lang/IllegalStateException");
    const char* m = (*e)->GetStringUTFChars(e, message, NULL);
    (*e)->ThrowNew(e, ex, m);
    (*e)->ReleaseStringUTFChars(e, message, m);
}

static jobject echo(JNIEnv* e, jclass c, jobject o) {
    (void)c;
    jobject g = (*e)->NewGlobalRef(e, o);
    jobject l = (*e)->NewLocalRef(e, g);
    (*e)->DeleteGlobalRef(e, g);
    return l;
}

static void* worker(void* arg) {
    (void)arg;
    JNIEnv* e;
    (*vm)->AttachCurrentThread(vm, &e, NULL);
    jmethodID bump = (*e)->GetStaticMethodID(e, test_class, "bump", "()V");
    for (int i = 0; i < 100; i++) (*e)->CallStaticVoidMethod(e, test_class, bump);
    (*vm)->DetachCurrentThread(vm);
    return NULL;
}

static jint threads(JNIEnv* e, jclass c, jint n) {
    (void)e, (void)c;
    pthread_t t[16];
    for (int i = 0; i < n && i < 16; i++) pthread_create(&t[i], NULL, worker, NULL);
    for (int i = 0; i < n && i < 16; i++) pthread_join(t[i], NULL);
    return n;
}

// Found by name: the short form, and two overloads in the long form.
JNIEXPORT jint JNICALL Java_Arm32JniTest_byName(JNIEnv* e, jclass c, jint v) {
    (void)e, (void)c;
    return v + 1;
}
JNIEXPORT jint JNICALL Java_Arm32JniTest_over__I(JNIEnv* e, jclass c, jint v) {
    (void)e, (void)c;
    return v * 2;
}
JNIEXPORT jint JNICALL Java_Arm32JniTest_over__Ljava_lang_String_2(JNIEnv* e, jclass c, jstring s) {
    (void)c;
    return (*e)->GetStringUTFLength(e, s);
}

// A signal for a thread that is in Java between native calls, the way the garbage collector
// stops the world: the handler acknowledges, waits in sigsuspend for the restart signal, and
// acknowledges again.
static sem_t ack;
static pthread_t prepared;
static volatile int handled_tid;

static void on_restart(int sig) { (void)sig; }

static void on_suspend(int sig) {
    (void)sig;
    handled_tid = gettid();
    sem_post(&ack);
    sigset_t m;
    sigfillset(&m);
    sigdelset(&m, SIGUSR1);
    sigsuspend(&m);
    sem_post(&ack);
}

static void prepare_signal(JNIEnv* e, jclass c) {
    (void)e, (void)c;
    sem_init(&ack, 0, 0);
    prepared = pthread_self();
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    // As the collector does: the restart signal stays blocked in the suspend handler until
    // sigsuspend lets it in, so it cannot be taken before the handler waits for it.
    sigemptyset(&sa.sa_mask);
    sigaddset(&sa.sa_mask, SIGUSR1);
    sa.sa_handler = on_suspend;
    sigaction(SIGUSR2, &sa, NULL);
    sigemptyset(&sa.sa_mask);
    sa.sa_handler = on_restart;
    sigaction(SIGUSR1, &sa, NULL);
}

static int wait_ack(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += 5;
    return sem_timedwait(&ack, &ts);
}

// Run on another thread while the prepared one waits in Java: 1, or which step failed.
static jint signal_prepared(JNIEnv* e, jclass c, jint tid) {
    (void)e, (void)c;
    if (pthread_kill(prepared, SIGUSR2) != 0) return -1;
    if (wait_ack() != 0) return -2;
    if (handled_tid != tid) return -3;
    if (pthread_kill(prepared, SIGUSR1) != 0) return -4;
    if (wait_ack() != 0) return -5;
    return 1;
}

// 1 when pthread_getattr_np's stack holds the caller's stack pointer. Called on the process's main
// thread (thread id = process id, like an app's UI thread). The guest C library takes a thread
// for the main one when its id equals getpid(), and then reads the "[stack]" line of
// /proc/self/maps; its getpid() is the agent's thread id, so this thread must get its own stack.
static jint stack_check(JNIEnv* e, jclass c) {
    (void)e, (void)c;
    pthread_attr_t attr;
    if (pthread_getattr_np(pthread_self(), &attr) != 0) return -1;
    void* base = NULL;
    size_t size = 0;
    pthread_attr_getstack(&attr, &base, &size);
    pthread_attr_destroy(&attr);
    char here;
    uintptr_t p = (uintptr_t)&here;
    if (p < (uintptr_t)base || p >= (uintptr_t)base + size) return -2;
    return 1;
}

// The plugin library binds its weak reference to this only if this library is global.
int arm32_global_probe(void) { return 1; }

// 1 when the plugin at `plugin`, loaded after this library, does not bind to its symbols, as with
// System.loadLibrary's RTLD_LOCAL. -1 when the plugin cannot be loaded.
static jint local_symbols(JNIEnv* e, jclass c, jstring plugin) {
    (void)c;
    const char* path = (*e)->GetStringUTFChars(e, plugin, NULL);
    void* h = dlopen(path, RTLD_NOW);
    (*e)->ReleaseStringUTFChars(e, plugin, path);
    int (*bound)(void) = h ? (int (*)(void))dlsym(h, "plugin_global_probe") : NULL;
    if (!bound) return -1;
    return bound() ? 0 : 1;
}

// The value of a new local reference (it grows with the number the thread holds), then a local
// frame pushed and left open.
static jint frame_probe(JNIEnv* e, jclass c) {
    jobject probe = (*e)->NewLocalRef(e, c);
    jint v = (jint)(intptr_t)probe;
    if ((*e)->PushLocalFrame(e, 4) == 0) (*e)->NewStringUTF(e, "left in an open frame");
    return v;
}

// Every element of a direct float buffer set to v, as many as its capacity says.
static void fill_floats(JNIEnv* e, jclass c, jobject buf, jfloat v) {
    (void)c;
    float* p = (*e)->GetDirectBufferAddress(e, buf);
    jlong n = (*e)->GetDirectBufferCapacity(e, buf);
    for (jlong i = 0; p && i < n; i++) p[i] = v;
}

// Bytes the guest heap has handed out.
static jint heap_in_use(JNIEnv* e, jclass c) {
    (void)e, (void)c;
    struct mallinfo m = mallinfo();
    return (jint)m.uordblks;
}

JNIEXPORT jint JNI_OnLoad(JavaVM* v, void* reserved) {
    (void)reserved;
    vm = v;
    JNIEnv* e;
    if ((*vm)->GetEnv(vm, (void**)&e, JNI_VERSION_1_6) != JNI_OK) return -1;
    jclass c = (*e)->FindClass(e, "Arm32JniTest");
    test_class = (*e)->NewGlobalRef(e, c);
    static const JNINativeMethod methods[] = {
        {"add", "(II)I", (void*)add},
        {"mix", "(IJIDFJBSCZ)J", (void*)mix},
        {"average", "([D)D", (void*)average},
        {"greet", "(Ljava/lang/String;)Ljava/lang/String;", (void*)greet},
        {"instanceSum", "(I)I", (void*)instance_sum},
        {"callbacks", "()I", (void*)callbacks},
        {"reverse", "([I)[I", (void*)reverse},
        {"fill", "(Ljava/nio/ByteBuffer;B)V", (void*)fill},
        {"wrap", "()Ljava/nio/ByteBuffer;", (void*)wrap},
        {"raise", "(Ljava/lang/String;)V", (void*)raise_exception},
        {"echo", "(Ljava/lang/Object;)Ljava/lang/Object;", (void*)echo},
        {"threads", "(I)I", (void*)threads},
        {"gl", "()I", (void*)media_gl},
        {"audio", "(I)I", (void*)media_audio},
        {"prepareSignal", "()V", (void*)prepare_signal},
        {"signalPrepared", "(I)I", (void*)signal_prepared},
        {"stackCheck", "()I", (void*)stack_check},
        {"localSymbols", "(Ljava/lang/String;)I", (void*)local_symbols},
        {"frameProbe", "()I", (void*)frame_probe},
        {"fillFloats", "(Ljava/nio/FloatBuffer;F)V", (void*)fill_floats},
        {"heapInUse", "()I", (void*)heap_in_use},
    };
    if ((*e)->RegisterNatives(e, c, methods, sizeof methods / sizeof methods[0]) != 0) return -1;
    return JNI_VERSION_1_6;
}
