// The guest side of the app bridge: the 32-bit process's main program.
//
// It hands the host the addresses of the guest linker's and heap's functions, then serves the
// host's requests. The main one creates a thread for a host thread: the runtime hands the clone
// to the asking host thread, which runs the C library's thread start up to thread_entry, where
// it parks and from then on runs guest calls as this thread.
#include <dlfcn.h>
#include <pthread.h>
#include <stdlib.h>

// Traps into the host runtime (traps.S).
void arm32_ready(const void* const* table);
int arm32_next_request(void);
void arm32_park(void);
void arm32_created(int error);

static void* thread_entry(void* arg) {
    (void)arg;
    // The host thread takes over here.
    arm32_park();
    return NULL;
}

int main(void) {
    // pthread_exit ends a host thread's guest thread when the host thread exits.
    static const void* const table[] = {
        (const void*)dlopen, (const void*)dlsym, (const void*)dlerror, (const void*)dlclose, (const void*)malloc, (const void*)free,
        (const void*)pthread_exit,
    };
    arm32_ready(table);
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    // Java threads run deep game code on these stacks.
    pthread_attr_setstacksize(&attr, 8 << 20);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    for (;;) {
        int kind = arm32_next_request();
        if (kind == 1) {
            pthread_t t;
            // The host thread that asked waits for this thread's clone; when there is none (no
            // room for another stack, for one) it is told so instead of waiting for good.
            arm32_created(pthread_create(&t, &attr, thread_entry, NULL));
        }
    }
}
