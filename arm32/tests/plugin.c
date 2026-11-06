// A guest library for the dlopen test and the app bridge tests.
#include <pthread.h>

static int calls = 0;
int plugin_add(int a, int b) { calls++; return a + b + 1000; }
int plugin_calls(void) { return calls; }

// Defined by the JNI test's library and by nothing this library depends on: the reference binds
// to that definition only when its library was loaded RTLD_GLOBAL (the linker looks in global
// libraries first), else it stays null. 1 when bound.
extern int arm32_global_probe(void) __attribute__((weak));
int plugin_global_probe(void) { return arm32_global_probe != 0; }

// Creates and joins n short threads. The bridge test runs it on several host threads at once, so
// guest threads are being created while other host threads are still being given guest threads
// of their own: each new thread must run its own start routine, not end up on a host thread that
// asked for a guest thread.
static void* echo_thread(void* arg) { return arg; }
int plugin_spawn(int n) {
    int done = 0;
    for (int i = 0; i < n; i++) {
        pthread_t t;
        if (pthread_create(&t, NULL, echo_thread, (void*)(long)i) != 0) break;
        void* r = 0;
        pthread_join(t, &r);
        if ((long)r == i) done++;
    }
    return done;
}
