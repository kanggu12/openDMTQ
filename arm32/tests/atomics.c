// Atomic updates are neither lost nor misordered, whichever way the runtime emulates the exclusive load and store
// (the global exclusive monitor, or with --fast-atomics a compare-and-swap against the value the load saw).
// Phases, each with a watchdog that fails the test when no thread made progress for four seconds, and an exact final check:
//   counters   threads adding to shared counters: 32-bit adds, compare-and-swap loops, four byte counters packed in
//              one word, 16-bit halves, and 64-bit adds (ldrexd)
//   sem        bionic sem_post / sem_wait / sem_timedwait: producers and consumers with the counts checked
//   spin       a spin lock taken with ldrex/strex and released with a plain store, protecting a plain counter
//   mutex      pthread mutex and condition variables under contention, a counter and a token passed round
//   aba        a stack of recycled nodes pushed and popped with ldrex/strex alone (no tag): correct with an exclusive
//              monitor, where a store between the load and the store-exclusive makes the latter fail; a
//              compare-and-swap cannot see such a store when it writes the value that was there
// Run with a phase name to run that one only.
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static atomic_long progress;
static const char* volatile phase_name = "start";
static atomic_int failures;

static void tick(void) { atomic_fetch_add(&progress, 1); }

static void check(const char* what, long long got, long long want) {
    if (got != want) {
        printf("FAIL %s: %lld, expected %lld (%lld lost)\n", what, got, want, want - got);
        atomic_fetch_add(&failures, 1);
    } else {
        printf("ok   %s: %lld\n", what, got);
    }
}

static long long now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000LL + t.tv_nsec / 1000000;
}

static unsigned rnd(unsigned* s) {
    unsigned x = *s ? *s : 2463534242u;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return *s = x;
}

// ----------------------------------------------------------------------------------------------------- counters

enum { kThreads = 12, kAdds = 60000 };
static volatile unsigned c_add, c_cas;
static volatile unsigned c_bytes;  // four byte counters
static volatile unsigned short c_half[2] __attribute__((aligned(4)));
static volatile unsigned long long c_wide __attribute__((aligned(8)));

static void* counter_thread(void* arg) {
    int me = (int)(intptr_t)arg;
    for (int i = 0; i < kAdds; i++) {
        __atomic_fetch_add(&c_add, 1, __ATOMIC_SEQ_CST);
        unsigned old = __atomic_load_n(&c_cas, __ATOMIC_RELAXED);
        while (!__atomic_compare_exchange_n(&c_cas, &old, old + 1, 1, __ATOMIC_SEQ_CST, __ATOMIC_RELAXED)) {}
        // Each thread's byte of the packed word: the byte's own counter, wrapping at 256, and every thread's wraps are
        // counted on the other side of the check.
        __atomic_fetch_add((volatile unsigned char*)&c_bytes + (me & 3), 1, __ATOMIC_SEQ_CST);
        __atomic_fetch_add(&c_half[me & 1], 1, __ATOMIC_SEQ_CST);
        __atomic_fetch_add(&c_wide, 3, __ATOMIC_SEQ_CST);
        if ((i & 1023) == 0) tick();
    }
    return NULL;
}

static void run_counters(void) {
    pthread_t t[kThreads];
    for (int i = 0; i < kThreads; i++) pthread_create(&t[i], NULL, counter_thread, (void*)(intptr_t)i);
    for (int i = 0; i < kThreads; i++) pthread_join(t[i], NULL);
    check("32-bit adds", c_add, (long long)kThreads * kAdds);
    check("compare-and-swap loops", c_cas, (long long)kThreads * kAdds);
    // Three threads per byte, each adding kAdds (mod 256 per byte).
    for (int b = 0; b < 4; b++) {
        char name[48];
        snprintf(name, sizeof name, "byte counter %d", b);
        check(name, (c_bytes >> (8 * b)) & 0xff, (3LL * kAdds) & 0xff);
    }
    for (int h = 0; h < 2; h++) {
        char name[48];
        snprintf(name, sizeof name, "16-bit counter %d", h);
        check(name, c_half[h], (6LL * kAdds) & 0xffff);
    }
    check("64-bit adds", (long long)c_wide, 3LL * kThreads * kAdds);
}

// ----------------------------------------------------------------------------------------------------- sem

enum { kProducers = 5, kConsumers = 7, kPosts = 20000 };
static sem_t sem_items;
static atomic_int consumed_total, consumed_timed;
static atomic_int consumers_stop, consumers_alive, wake_posts;

static void* sem_producer(void* arg) {
    unsigned s = (unsigned)(intptr_t)arg * 11 | 1;
    for (int i = 0; i < kPosts; i++) {
        sem_post(&sem_items);
        if (rnd(&s) % 16 == 0) sched_yield();
        if ((i & 255) == 0) tick();
    }
    return NULL;
}
static void* sem_consumer_body(void* arg) {
    int timed = (int)(intptr_t)arg & 1;
    for (;;) {
        int r;
        if (timed) {
            struct timespec ts;
            clock_gettime(CLOCK_REALTIME, &ts);
            ts.tv_nsec += 3000000;
            if (ts.tv_nsec >= 1000000000) { ts.tv_nsec -= 1000000000; ts.tv_sec++; }
            r = sem_timedwait(&sem_items, &ts);
            if (r != 0 && errno == ETIMEDOUT) {
                if (atomic_load(&consumers_stop)) {
                    // The producers are done: what is left is taken without waiting, and an empty sem ends this.
                    if (sem_trywait(&sem_items) == 0) {
                        atomic_fetch_add(&consumed_total, 1);
                        atomic_fetch_add(&consumed_timed, 1);
                        continue;
                    }
                    break;
                }
                continue;
            }
            if (r != 0 && errno == EINTR) continue;
        } else {
            // The plain wait ends when the stop flag is up and the count is empty: a poll with a timeout would do it,
            // so the plain consumers take what is there without blocking once the producers are done.
            if (atomic_load(&consumers_stop)) {
                if (sem_trywait(&sem_items) == 0) {
                    atomic_fetch_add(&consumed_total, 1);
                    continue;
                }
                break;
            }
            r = sem_wait(&sem_items);
            if (r != 0) continue;
            // sem_wait may be the last thing a consumer does before the stop: counted all the same.
        }
        atomic_fetch_add(&consumed_total, 1);
        tick();
    }
    return NULL;
}

static void* sem_consumer(void* arg) {
    sem_consumer_body(arg);
    atomic_fetch_sub(&consumers_alive, 1);
    return NULL;
}

static void run_sem(void) {
    pthread_t p[kProducers], c[kConsumers];
    sem_init(&sem_items, 0, 0);
    atomic_store(&consumers_alive, kConsumers);
    for (int i = 0; i < kConsumers; i++) pthread_create(&c[i], NULL, sem_consumer, (void*)(intptr_t)i);
    for (int i = 0; i < kProducers; i++) pthread_create(&p[i], NULL, sem_producer, (void*)(intptr_t)(i + 1));
    for (int i = 0; i < kProducers; i++) pthread_join(p[i], NULL);
    // Everything posted is waited for before the consumers are told to stop; the plain consumers sleep in sem_wait, so
    // a last post per consumer wakes them to see the flag.
    // No tick here: a post that never reaches a consumer must stop the progress for the watchdog to see.
    while (atomic_load(&consumed_total) < kProducers * kPosts) usleep(2000);
    atomic_store(&consumers_stop, 1);
    // Wake-up posts until every consumer is out: a timed one may take one meant for a sleeper.
    while (atomic_load(&consumers_alive) > 0) {
        sem_post(&sem_items);
        atomic_fetch_add(&wake_posts, 1);
        usleep(20000);
    }
    for (int i = 0; i < kConsumers; i++) pthread_join(c[i], NULL);
    int left = 0;
    sem_getvalue(&sem_items, &left);
    // Every post, the producers' and the wake-up ones, was consumed or is still in the count.
    check("posts consumed plus left", atomic_load(&consumed_total) + left, kProducers * kPosts + atomic_load(&wake_posts));
    printf("     (%d consumed, %d of them by timed waits, %d wake-up posts left)\n", atomic_load(&consumed_total), atomic_load(&consumed_timed), left);
}

// ----------------------------------------------------------------------------------------------------- spin

enum { kSpinThreads = 10, kSpinRounds = 30000 };
static volatile unsigned spin_lock;
static unsigned spin_counter;  // plain: the lock alone protects it

static inline void spin_acquire(volatile unsigned* l) {
    unsigned v, f;
    __asm__ volatile(
        "1: ldrex %0, [%2]\n"
        "   cmp %0, #0\n"
        "   bne 1b\n"
        "   mov %0, #1\n"
        "   strex %1, %0, [%2]\n"
        "   cmp %1, #0\n"
        "   bne 1b\n"
        "   dmb ish\n"
        : "=&r"(v), "=&r"(f)
        : "r"(l)
        : "cc", "memory");
}
static inline void spin_release(volatile unsigned* l) {
    __asm__ volatile("dmb ish" ::: "memory");
    *l = 0;  // a plain store, as the usual unlock
}
static void* spin_thread(void* arg) {
    (void)arg;
    for (int i = 0; i < kSpinRounds; i++) {
        spin_acquire(&spin_lock);
        unsigned v = spin_counter;
        spin_counter = v + 1;
        spin_release(&spin_lock);
        if ((i & 1023) == 0) tick();
    }
    return NULL;
}
static void run_spin(void) {
    pthread_t t[kSpinThreads];
    for (int i = 0; i < kSpinThreads; i++) pthread_create(&t[i], NULL, spin_thread, NULL);
    for (int i = 0; i < kSpinThreads; i++) pthread_join(t[i], NULL);
    check("spin lock counter", spin_counter, (long long)kSpinThreads * kSpinRounds);
}

// ----------------------------------------------------------------------------------------------------- mutex

enum { kMutexThreads = 12, kMutexRounds = 1200 };
static pthread_mutex_t mm = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t mc = PTHREAD_COND_INITIALIZER;
static long m_counter;
static int m_turn;
static void* mutex_thread(void* arg) {
    int me = (int)(intptr_t)arg;
    for (int i = 0; i < kMutexRounds; i++) {
        pthread_mutex_lock(&mm);
        m_counter++;
        pthread_mutex_unlock(&mm);
        // A token passed round the threads: each waits for its turn on the condition variable.
        pthread_mutex_lock(&mm);
        while (m_turn != me) pthread_cond_wait(&mc, &mm);
        m_turn = (m_turn + 1) % kMutexThreads;
        pthread_cond_broadcast(&mc);
        pthread_mutex_unlock(&mm);
        if ((i & 63) == 0) tick();
    }
    return NULL;
}
static void run_mutex(void) {
    pthread_t t[kMutexThreads];
    for (int i = 0; i < kMutexThreads; i++) pthread_create(&t[i], NULL, mutex_thread, (void*)(intptr_t)i);
    for (int i = 0; i < kMutexThreads; i++) pthread_join(t[i], NULL);
    check("mutex counter", m_counter, (long long)kMutexThreads * kMutexRounds);
    check("token laps", m_turn, 0);
}

// ----------------------------------------------------------------------------------------------------- aba

enum { kNodes = 6, kAbaThreads = 8, kAbaOps = 60000 };
struct node {
    struct node* next;  // first: the asm reads it at offset 0
    long owner_uses;    // plain: only the thread that popped the node touches it
    long pad[6];
};
static struct node nodes[kNodes];
static struct node* volatile stack_head;

static inline void stack_push(struct node* n) {
    unsigned f;
    struct node* h;
    __asm__ volatile(
        "1: ldrex %0, [%3]\n"
        "   str %0, [%2]\n"
        "   dmb ish\n"
        "   strex %1, %2, [%3]\n"
        "   cmp %1, #0\n"
        "   bne 1b\n"
        : "=&r"(h), "=&r"(f)
        : "r"(n), "r"(&stack_head)
        : "cc", "memory");
}
// The pop reads the next pointer between the load-exclusive and the store-exclusive: with a monitor, a push and pop of
// other threads in between make the store-exclusive fail; with a compare-and-swap against the head, it succeeds when
// the head is the same node again, and stores a next that is stale.
static inline struct node* stack_pop(void) {
    unsigned f;
    struct node *h, *next;
    __asm__ volatile(
        "1: ldrex %0, [%3]\n"
        "   cmp %0, #0\n"
        "   beq 2f\n"
        "   ldr %2, [%0]\n"
        "   strex %1, %2, [%3]\n"
        "   cmp %1, #0\n"
        "   bne 1b\n"
        "   b 3f\n"
        "2: clrex\n"
        "3: dmb ish\n"
        : "=&r"(h), "=&r"(f), "=&r"(next)
        : "r"(&stack_head)
        : "cc", "memory");
    return h;
}
static atomic_long aba_pops;
static void* aba_thread(void* arg) {
    unsigned s = (unsigned)(intptr_t)arg * 13 | 1;
    for (int i = 0; i < kAbaOps; i++) {
        struct node* n = stack_pop();
        if (!n) {
            sched_yield();
            continue;
        }
        n->owner_uses++;  // two threads owning one node lose counts here
        atomic_fetch_add(&aba_pops, 1);
        if (rnd(&s) % 8 == 0) sched_yield();
        stack_push(n);
        if ((i & 1023) == 0) tick();
    }
    return NULL;
}
static void run_aba(void) {
    for (int i = 0; i < kNodes; i++) {
        nodes[i].owner_uses = 0;
        stack_push(&nodes[i]);
    }
    pthread_t t[kAbaThreads];
    for (int i = 0; i < kAbaThreads; i++) pthread_create(&t[i], NULL, aba_thread, (void*)(intptr_t)(i + 1));
    for (int i = 0; i < kAbaThreads; i++) pthread_join(t[i], NULL);
    // Every node is on the stack exactly once.
    int seen = 0, cyc = 0;
    for (struct node* n = stack_head; n && seen < 100; n = n->next) {
        seen++;
        if (seen > kNodes) cyc = 1;
    }
    check("nodes on the stack at the end", cyc ? 100 : seen, kNodes);
    long total = 0;
    for (int i = 0; i < kNodes; i++) total += nodes[i].owner_uses;
    check("pops counted by the nodes' owners", total, atomic_load(&aba_pops));
}

// ----------------------------------------------------------------------------------------------------- driver

static void* watchdog(void* arg) {
    (void)arg;
    long last = -1;
    int still = 0;
    for (;;) {
        usleep(100000);
        long p = atomic_load(&progress);
        if (p != last) {
            last = p;
            still = 0;
            continue;
        }
        if (++still >= 50) {
            printf("FAIL phase %s: no progress for 5 seconds after %ld steps: a thread is stuck\n", phase_name, p);
            printf("SOME CHECKS FAILED\n");
            _exit(1);
        }
    }
}

#define PHASE(name, fn)                                    \
    do {                                                   \
        if (!only || strstr(name, only)) {                 \
            phase_name = name;                             \
            long long t0 = now_ms();                       \
            fn();                                          \
            printf("     %s took %lld ms\n", name, now_ms() - t0); \
        }                                                  \
    } while (0)

int main(int argc, char** argv) {
    const char* only = argc > 1 ? argv[1] : NULL;
    setvbuf(stdout, NULL, _IONBF, 0);
    pthread_t wd;
    pthread_create(&wd, NULL, watchdog, NULL);
    PHASE("counters", run_counters);
    PHASE("sem", run_sem);
    PHASE("spin", run_spin);
    PHASE("mutex", run_mutex);
    PHASE("aba", run_aba);
    if (atomic_load(&failures)) {
        printf("SOME CHECKS FAILED\n");
        return 1;
    }
    printf("ALL CHECKS PASSED\n");
    return 7;
}
