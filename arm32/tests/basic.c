// First guest test: C library start-up, stdio, heap, time, files, floating point and threads.
// Prints one line per check and exits with 7 when every check passed.
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static long counter = 0;

static void* worker(void* arg) {
    for (int i = 0; i < 100000; i++) {
        pthread_mutex_lock(&lock);
        counter++;
        pthread_mutex_unlock(&lock);
    }
    return arg;
}

int main(int argc, char** argv) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    printf("arm32 basic test: argc=%d argv[0]=%s pid=%d\n", argc, argv[0], getpid());
    char* p = malloc(1 << 20);
    CHECK("malloc 1 MB", p != NULL);
    memset(p, 0x5a, 1 << 20);
    free(p);
    struct timespec ts;
    CHECK("clock_gettime", clock_gettime(CLOCK_MONOTONIC, &ts) == 0 && (ts.tv_sec > 0 || ts.tv_nsec > 0));
    volatile double d = 2.0;
    CHECK("sqrt and printf %f", fabs(sqrt(d) - 1.41421356) < 1e-6);
    char buf[64];
    snprintf(buf, sizeof buf, "%.3f %d %s", 3.14159, -42, "x");
    CHECK("snprintf", strcmp(buf, "3.142 -42 x") == 0);
    FILE* f = fopen("/proc/self/maps", "r");
    char line[256] = "";
    CHECK("read /proc/self/maps", f && fgets(line, sizeof line, f));
    if (f) fclose(f);
    printf("     first map: %s", line);
    pthread_t threads[4];
    for (int i = 0; i < 4; i++) pthread_create(&threads[i], NULL, worker, (void*)(long)i);
    long sum = 0;
    for (int i = 0; i < 4; i++) {
        void* ret;
        pthread_join(threads[i], &ret);
        sum += (long)ret;
    }
    CHECK("4 threads, mutex counter", counter == 400000 && sum == 6);
    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
