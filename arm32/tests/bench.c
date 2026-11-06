// Speed of translated code against native: integer work (sieve), float work (matrix multiply),
// memory bandwidth (memcpy), atomic increments (LDREX/STREX, as in locks and reference counts)
// and clock_gettime (a system call in the guest, which has no vDSO). Build it for the guest and
// for the host and compare.
#include <arm_neon.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

// Four threads increment one counter; each keeps its slowest single increment, where a stall
// (a thread preempted while holding a lock all threads need) shows.
static volatile int shared_counter;
static void* hammer(void* arg) {
    double* worst = arg;
    for (int i = 0; i < 1000000; i++) {
        double a = now();
        __atomic_fetch_add(&shared_counter, 1, __ATOMIC_SEQ_CST);
        double d = now() - a;
        if (d > *worst) *worst = d;
    }
    return NULL;
}

int main(void) {
    double t0 = now();
    int n = 20000000, count = 0;
    char* sieve = calloc(n, 1);
    for (int i = 2; i < n; i++) {
        if (sieve[i]) continue;
        count++;
        for (long long j = (long long)i * i; j < n; j += i) sieve[j] = 1;
    }
    double t1 = now();
    int N = 300;
    float *a = malloc(N * N * 4), *b = malloc(N * N * 4), *r = malloc(N * N * 4);
    for (int i = 0; i < N * N; i++) { a[i] = (i % 7) * 0.5f; b[i] = (i % 5) * 0.25f; }
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            float acc = 0;
            for (int k = 0; k < N; k++) acc += a[i * N + k] * b[k * N + j];
            r[i * N + j] = acc;
        }
    double t2 = now();
    size_t size = 64 << 20;
    char *x = malloc(size), *y = malloc(size);
    memset(x, 1, size);
    for (int i = 0; i < 10; i++) memcpy(y, x, size);
    double t3 = now();
    static volatile int counter;
    int m = 5000000;
    for (int i = 0; i < m; i++) __atomic_fetch_add(&counter, 1, __ATOMIC_SEQ_CST);
    double t4 = now();
    int c = 200000;
    for (int i = 0; i < c; i++) now();
    double t5 = now();
    // NEON float multiply-adds over an array, as audio mixing and vector maths do.
    int len = 4096, reps = 20000;
    float *v = malloc(len * 4), *w = malloc(len * 4);
    for (int i = 0; i < len; i++) { v[i] = i * 0.001f; w[i] = 1.0001f; }
    float32x4_t acc = vdupq_n_f32(0);
    for (int rep = 0; rep < reps; rep++) {
        for (int i = 0; i < len; i += 4) {
            float32x4_t a4 = vld1q_f32(v + i);
            acc = vmlaq_f32(acc, a4, vld1q_f32(w + i));
            vst1q_f32(v + i, vmulq_n_f32(a4, 0.9999f));
        }
    }
    double t6 = now();
    pthread_t th[4];
    double worst[4] = {0, 0, 0, 0};
    for (int i = 0; i < 4; i++) pthread_create(&th[i], NULL, hammer, &worst[i]);
    for (int i = 0; i < 4; i++) pthread_join(th[i], NULL);
    double t7 = now(), longest = 0;
    for (int i = 0; i < 4; i++) if (worst[i] > longest) longest = worst[i];
    float lanes[4];
    vst1q_f32(lanes, acc);
    double sum = lanes[0] + lanes[1] + lanes[2] + lanes[3];
    for (int i = 0; i < N * N; i++) sum += r[i];
    printf("sieve  %.3f s (%d primes)\nmatmul %.3f s (sum %.1f)\nmemcpy %.3f s (%d)\n", t1 - t0, count, t2 - t1, sum, t3 - t2, y[size - 1]);
    printf("atomic %.1f ns per increment\nclock  %.0f ns per clock_gettime\n", (t4 - t3) / m * 1e9, (t5 - t4) / c * 1e9);
    printf("shared %.3f s for 4 x 1M increments (%d), longest single increment %.2f ms\n", t7 - t6, shared_counter, longest * 1e3);
    printf("neon   %.3f s (%.1f ns per 4-wide multiply-add and multiply)\n", t6 - t5, (t6 - t5) / ((double)reps * len / 4) * 1e9);
    return 0;
}
