// Code replaced at an address is seen by every thread, not only by the one that replaced it. A
// second thread runs a function from an executable page; the main thread unmaps the page, maps new
// code at the same address and flushes the cache, as a loader does when it reuses an address. On
// ARM Linux the flush reaches every CPU, so the second thread must run the new code: a stale
// translation of the old page in its own code cache returns the old value.
#include <pthread.h>
#include <semaphore.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static sem_t go, done;
static int (*volatile fn)(void);
static volatile int result;

// Calls fn whenever told to, so its translation lives in this thread's code cache.
static void* runner(void* arg) {
    (void)arg;
    for (int i = 0; i < 3; i++) {
        sem_wait(&go);
        result = fn();
        sem_post(&done);
    }
    return NULL;
}

// A page holding "mov r0, #value; bx lr" (ARM state), at `at` when given.
static void* put_code(void* at, unsigned value) {
    void* p = mmap(at, 4096, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS | (at ? MAP_FIXED : 0), -1, 0);
    if (p == MAP_FAILED) return NULL;
    const unsigned code[2] = {0xe3a00000u | value, 0xe12fff1eu};
    memcpy(p, code, sizeof code);
    __builtin___clear_cache((char*)p, (char*)p + sizeof code);
    return p;
}

static int run_once(void) {
    sem_post(&go);
    sem_wait(&done);
    return result;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    sem_init(&go, 0, 0);
    sem_init(&done, 0, 0);
    void* page = put_code(NULL, 1);
    if (!page) {
        printf("FAIL mmap\nSOME CHECKS FAILED\n");
        return 1;
    }
    fn = (int (*)(void))page;
    pthread_t t;
    pthread_create(&t, NULL, runner, NULL);
    CHECK("another thread runs the code", run_once() == 1);
    // New code at the same address: unmapped, mapped again, written and flushed.
    munmap(page, 4096);
    void* again = put_code(page, 2);
    CHECK("the new mapping is at the same address", again == page);
    CHECK("the other thread runs the replaced code", run_once() == 2);
    // Rewritten in place (writable and executable all along) and flushed.
    const unsigned code3 = 0xe3a00003u;
    memcpy(page, &code3, sizeof code3);
    __builtin___clear_cache((char*)page, (char*)page + 4);
    CHECK("the other thread runs code rewritten in place", run_once() == 3);
    pthread_join(t, NULL);
    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
