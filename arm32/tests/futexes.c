// Futex wake-ups are never lost: many threads wait and wake in the patterns the C library, the Java VM and the game's
// job system use, and a wake that does not reach a waiter that was about to sleep leaves it asleep for good.
// Eight phases, each with threads that sleep without a timeout (a lost wake hangs them) and a watchdog that
// fails the test when no thread made progress for a few seconds, instead of hanging it:
//   mailbox   pairs of threads handing a counter to each other, the waits plain and with bitsets, the wakes too
//   barrier   a generation barrier of eight threads, the last one to arrive wakes all the others
//   timed     waits with relative and absolute timeouts on both clocks, which must end in time, not early
//   signals   the mailbox again with signals (handlers without SA_RESTART, so waits return EINTR) at all its threads
//   requeue   a condition variable the way the C library of a desktop builds it: wake one, requeue the rest to the mutex
//   wakeop    FUTEX_WAKE_OP waking two words at once
//   churn     batches of threads made, started with one wake and joined (the join is a futex wait too)
//   pthread   semaphores in a ring, a mutex and condition variables with and without timeouts
#include <errno.h>
#include <limits.h>
#include <linux/futex.h>
#include <pthread.h>
#include <sched.h>
#include <semaphore.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

typedef _Atomic unsigned word;

static atomic_long progress;
static const char* volatile phase_name = "start";
static atomic_int failures;

static long futex(word* addr, int op, unsigned val, const struct timespec* timeout, word* addr2, unsigned val3) {
    return syscall(SYS_futex, addr, op | FUTEX_PRIVATE_FLAG, val, timeout, addr2, val3);
}
// The requeue calls carry a count where the others have a timeout.
static long futex_count(word* addr, int op, unsigned val, long count, word* addr2, unsigned val3) {
    return syscall(SYS_futex, addr, op | FUTEX_PRIVATE_FLAG, val, (void*)(intptr_t)count, addr2, val3);
}

static void tick(void) { atomic_fetch_add(&progress, 1); }

static unsigned rnd(unsigned* s) {
    unsigned x = *s ? *s : 2463534242u;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return *s = x;
}

static long long now_ns(clockid_t c) {
    struct timespec t;
    clock_gettime(c, &t);
    return t.tv_sec * 1000000000LL + t.tv_nsec;
}

static void sig_noop(int sig) { (void)sig; }

// A thread's pause at random, so that the interleavings differ from round to round: nothing, a yield or a spin.
static void jitter(unsigned* s) {
    unsigned r = rnd(s) % 8;
    if (r == 0) sched_yield();
    else if (r == 1) for (volatile int i = 0, n = (int)(rnd(s) % 400); i < n; i++) {}
}

// Waits while *w == old: a plain wait or one with a bitset, as the caller's choice says. Comes back on any wake, and on
// EINTR and EAGAIN, so that the caller looks at the word again.
static void wait_while(word* w, unsigned old, unsigned* s) {
    if (rnd(s) & 1) futex(w, FUTEX_WAIT, old, NULL, NULL, 0);
    else futex(w, FUTEX_WAIT_BITSET, old, NULL, NULL, (rnd(s) & 2) ? 0x4u : FUTEX_BITSET_MATCH_ANY);
}
static void wake_some(word* w, int n, unsigned* s) {
    if (rnd(s) & 1) futex(w, FUTEX_WAKE, (unsigned)n, NULL, NULL, 0);
    else futex(w, FUTEX_WAKE_BITSET, (unsigned)n, NULL, NULL, (rnd(s) & 2) ? 0x4u : FUTEX_BITSET_MATCH_ANY);
}

// ----------------------------------------------------------------------------------------------------- mailbox

enum { kPairs = 6 };
static unsigned mailbox_rounds = 12000;
struct pair {
    word req;
    char pad1[60];
    word ack;
    char pad2[60];
} pairs[kPairs];
static atomic_int flood_on;

static void* mailbox_server(void* arg) {
    struct pair* p = arg;
    unsigned s = (unsigned)(uintptr_t)p | 1;
    for (unsigned i = 1; i <= mailbox_rounds; i++) {
        unsigned cur;
        while ((cur = atomic_load(&p->req)) < i) wait_while(&p->req, cur, &s);
        jitter(&s);
        atomic_store(&p->ack, i);
        wake_some(&p->ack, 1, &s);
        tick();
    }
    return NULL;
}
static void* mailbox_client(void* arg) {
    struct pair* p = arg;
    unsigned s = (unsigned)(uintptr_t)p * 3 | 1;
    for (unsigned i = 1; i <= mailbox_rounds; i++) {
        jitter(&s);
        atomic_store(&p->req, i);
        wake_some(&p->req, 1, &s);
        unsigned cur;
        while ((cur = atomic_load(&p->ack)) < i) wait_while(&p->ack, cur, &s);
        tick();
    }
    return NULL;
}

static pthread_t mailbox_threads[2 * kPairs];
static void run_mailbox(int pair_count) {
    memset(pairs, 0, sizeof pairs);
    for (int i = 0; i < pair_count; i++) {
        pthread_create(&mailbox_threads[2 * i], NULL, mailbox_server, &pairs[i]);
        pthread_create(&mailbox_threads[2 * i + 1], NULL, mailbox_client, &pairs[i]);
    }
}
static void join_mailbox(int pair_count) {
    for (int i = 0; i < 2 * pair_count; i++) pthread_join(mailbox_threads[i], NULL);
}

// The signals phase: every thread of the mailbox gets signals, SIGUSR1 handled and SIGUSR2 the same.
static void* flooder(void* arg) {
    (void)arg;
    unsigned s = 77;
    while (atomic_load(&flood_on)) {
        int k = (int)(rnd(&s) % (2 * kPairs));
        pthread_kill(mailbox_threads[k], (rnd(&s) & 1) ? SIGUSR1 : SIGUSR2);
        if (rnd(&s) % 4 == 0) sched_yield();
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- barrier

enum { kBarrierThreads = 8, kBarrierRounds = 15000 };
static word barrier_gen, barrier_count;
static void* barrier_thread(void* arg) {
    unsigned s = (unsigned)(uintptr_t)arg * 5 | 1;
    for (int i = 0; i < kBarrierRounds; i++) {
        jitter(&s);
        unsigned g = atomic_load(&barrier_gen);
        if (atomic_fetch_add(&barrier_count, 1) + 1 == kBarrierThreads) {
            atomic_store(&barrier_count, 0);
            atomic_fetch_add(&barrier_gen, 1);
            futex(&barrier_gen, FUTEX_WAKE, INT_MAX, NULL, NULL, 0);
        } else {
            while (atomic_load(&barrier_gen) == g) futex(&barrier_gen, FUTEX_WAIT, g, NULL, NULL, 0);
        }
        tick();
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- timed

enum { kTimedThreads = 6, kTimedRounds = 1500 };
static word timed_word;
static atomic_int timed_wakes;
static atomic_int timed_stop;
static void* timed_thread(void* arg) {
    unsigned s = (unsigned)(uintptr_t)arg * 7 | 1;
    for (int i = 0; i < kTimedRounds; i++) {
        long long wait_ns = (long long)(rnd(&s) % 3000) * 1000 + 100000;  // 0.1 to 3.1 ms
        int mode = (int)(rnd(&s) % 3);
        struct timespec ts;
        long long start = now_ns(CLOCK_MONOTONIC), limit;
        long r;
        if (mode == 0) {
            ts.tv_sec = wait_ns / 1000000000LL;
            ts.tv_nsec = wait_ns % 1000000000LL;
            r = futex(&timed_word, FUTEX_WAIT, 0, &ts, NULL, 0);
        } else {
            clockid_t c = mode == 1 ? CLOCK_MONOTONIC : CLOCK_REALTIME;
            long long at = now_ns(c) + wait_ns;
            ts.tv_sec = at / 1000000000LL;
            ts.tv_nsec = at % 1000000000LL;
            r = futex(&timed_word, FUTEX_WAIT_BITSET | (mode == 2 ? FUTEX_CLOCK_REALTIME : 0), 0, &ts, NULL,
                      FUTEX_BITSET_MATCH_ANY);
        }
        limit = now_ns(CLOCK_MONOTONIC) - start;
        if (r < 0 && errno == ETIMEDOUT) {
            // Not early (a millisecond of slack for the clocks' granularity), and not seconds late.
            if (limit < wait_ns - 1000000 || limit > wait_ns + 1000000000LL) {
                printf("FAIL timed mode %d: a wait of %lld us ended with a timeout after %lld us\n", mode, wait_ns / 1000, limit / 1000);
                atomic_fetch_add(&failures, 1);
            }
        } else if (r < 0 && errno != EINTR && errno != EAGAIN) {
            printf("FAIL timed mode %d: errno %d\n", mode, errno);
            atomic_fetch_add(&failures, 1);
        }
        // A wait on a value the word does not have must not sleep at all.
        long q = futex(&timed_word, FUTEX_WAIT, 12345, &ts, NULL, 0);
        if (q != -1 || errno != EAGAIN) {
            printf("FAIL timed: a wait on the wrong value returned %ld, errno %d\n", q, errno);
            atomic_fetch_add(&failures, 1);
        }
        tick();
    }
    return NULL;
}
static void* timed_waker(void* arg) {
    (void)arg;
    unsigned s = 99;
    while (!atomic_load(&timed_stop)) {
        if (futex(&timed_word, FUTEX_WAKE, 1, NULL, NULL, 0) > 0) atomic_fetch_add(&timed_wakes, 1);
        for (volatile int i = 0, n = (int)(rnd(&s) % 5000); i < n; i++) {}
        sched_yield();
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- requeue

enum { kQueueWaiters = 6, kQueueRounds = 2500 };
static word cv_seq, mx, arrived, done_count, generation, epoch;
static void lock_mx(void) {
    unsigned c = 0;
    if (atomic_compare_exchange_strong(&mx, &c, 1)) return;
    if (c != 2) c = atomic_exchange(&mx, 2);
    while (c != 0) {
        futex(&mx, FUTEX_WAIT, 2, NULL, NULL, 0);
        c = atomic_exchange(&mx, 2);
    }
}
// After a wait on the condition: the mutex is taken as contended, because waiters requeued to it sleep on it and only
// an unlock that finds it contended wakes the next of them (the C library does the same).
static void lock_mx_contended(void) {
    while (atomic_exchange(&mx, 2) != 0) futex(&mx, FUTEX_WAIT, 2, NULL, NULL, 0);
}
static void unlock_mx(void) {
    if (atomic_exchange(&mx, 0) == 2) futex(&mx, FUTEX_WAKE, 1, NULL, NULL, 0);
}
static void* queue_waiter(void* arg) {
    (void)arg;
    for (unsigned r = 0; r < kQueueRounds; r++) {
        lock_mx();
        atomic_fetch_add(&arrived, 1);
        while (atomic_load(&generation) <= r) {
            unsigned seq = atomic_load(&cv_seq);
            unlock_mx();
            futex(&cv_seq, FUTEX_WAIT, seq, NULL, NULL, 0);
            lock_mx_contended();
        }
        atomic_fetch_add(&done_count, 1);
        unlock_mx();
        tick();
        // The next round only when the broadcaster has reset the counts of this one.
        while (atomic_load(&epoch) < r + 1) sched_yield();
    }
    return NULL;
}
static void* queue_caster(void* arg) {
    (void)arg;
    for (unsigned r = 0; r < kQueueRounds; r++) {
        while (atomic_load(&arrived) < kQueueWaiters) sched_yield();
        lock_mx();
        atomic_fetch_add(&generation, 1);
        unsigned seq = atomic_fetch_add(&cv_seq, 1) + 1;
        // Wake one, requeue the others to the mutex, which is ours and marked contended so that its unlock wakes them.
        atomic_store(&mx, 2);
        long n = futex_count(&cv_seq, FUTEX_CMP_REQUEUE, 1, INT_MAX, &mx, seq);
        (void)n;
        unlock_mx();
        while (atomic_load(&done_count) < kQueueWaiters) sched_yield();
        lock_mx();
        atomic_store(&arrived, 0);
        atomic_store(&done_count, 0);
        atomic_store(&epoch, r + 1);
        unlock_mx();
        tick();
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- wakeop

enum { kOpRounds = 4000 };
static word op_a, op_b, op_ack;
static void* op_waiter(void* arg) {
    word* w = arg;
    for (unsigned i = 1; i <= kOpRounds; i++) {
        unsigned cur;
        while ((cur = atomic_load(w)) < i) futex(w, FUTEX_WAIT, cur, NULL, NULL, 0);
        atomic_fetch_add(&op_ack, 1);
        futex(&op_ack, FUTEX_WAKE, 1, NULL, NULL, 0);
        tick();
    }
    return NULL;
}
static void* op_driver(void* arg) {
    (void)arg;
    unsigned s = 5;
    for (unsigned i = 1; i <= kOpRounds; i++) {
        jitter(&s);
        // op_b gets +1 (FUTEX_OP_ADD), and its waiter wakes when the old value of it is below 4095 (FUTEX_OP_CMP_LT).
        atomic_store(&op_a, i);
        unsigned enc = (1u << 28) | (2u << 24) | (1u << 12) | 0xfffu;
        long woke = futex_count(&op_a, FUTEX_WAKE_OP, 1, 1, &op_b, enc);
        // The ack of both waiters: a lost wake of either leaves this wait for good.
        unsigned cur;
        while ((cur = atomic_load(&op_ack)) < 2 * i) futex(&op_ack, FUTEX_WAIT, cur, NULL, NULL, 0);
        (void)woke;
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- churn

enum { kChurnBatch = 16, kChurnBatches = 120 };
static word churn_go;
static word churn_ready;
static sem_t churn_done;
static void* churn_thread(void* arg) {
    (void)arg;
    atomic_fetch_add(&churn_ready, 1);
    futex(&churn_ready, FUTEX_WAKE, 1, NULL, NULL, 0);
    while (atomic_load(&churn_go) == 0) futex(&churn_go, FUTEX_WAIT, 0, NULL, NULL, 0);
    sem_post(&churn_done);
    return NULL;
}
static void* churn_parent(void* arg) {
    (void)arg;
    sem_init(&churn_done, 0, 0);
    for (int b = 0; b < kChurnBatches; b++) {
        pthread_t t[kChurnBatch];
        atomic_store(&churn_go, 0);
        atomic_store(&churn_ready, 0);
        for (int i = 0; i < kChurnBatch; i++) pthread_create(&t[i], NULL, churn_thread, NULL);
        unsigned cur;
        while ((cur = atomic_load(&churn_ready)) < kChurnBatch) futex(&churn_ready, FUTEX_WAIT, cur, NULL, NULL, 0);
        atomic_store(&churn_go, 1);
        futex(&churn_go, FUTEX_WAKE, INT_MAX, NULL, NULL, 0);
        for (int i = 0; i < kChurnBatch; i++) while (sem_wait(&churn_done) != 0) {}
        for (int i = 0; i < kChurnBatch; i++) pthread_join(t[i], NULL);
        tick();
    }
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- pthread

enum { kRing = 10, kLaps = 2500 };
static sem_t ring[kRing];
static void* ring_thread(void* arg) {
    int me = (int)(intptr_t)arg;
    for (int lap = 0; lap < kLaps; lap++) {
        while (sem_wait(&ring[me]) != 0) {}
        sem_post(&ring[(me + 1) % kRing]);
        tick();
    }
    return NULL;
}

enum { kItems = 20000, kConsumers = 8 };
static pthread_mutex_t qm = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t qc = PTHREAD_COND_INITIALIZER;
static int queued, consumed, produced;
static void* consumer(void* arg) {
    int timed = (int)(intptr_t)arg & 1;
    pthread_mutex_lock(&qm);
    for (;;) {
        while (queued == 0 && produced < kItems) {
            if (timed) {
                struct timespec ts;
                clock_gettime(CLOCK_REALTIME, &ts);
                ts.tv_nsec += 2000000;
                if (ts.tv_nsec >= 1000000000) { ts.tv_nsec -= 1000000000; ts.tv_sec++; }
                pthread_cond_timedwait(&qc, &qm, &ts);
            } else {
                pthread_cond_wait(&qc, &qm);
            }
        }
        if (queued == 0) break;
        queued--;
        consumed++;
        tick();
    }
    pthread_mutex_unlock(&qm);
    return NULL;
}
static void* producer(void* arg) {
    unsigned s = (unsigned)(uintptr_t)arg | 1;
    for (;;) {
        pthread_mutex_lock(&qm);
        if (produced >= kItems) {
            pthread_mutex_unlock(&qm);
            break;
        }
        produced++;
        queued++;
        if (rnd(&s) % 5 == 0) pthread_cond_broadcast(&qc);
        else pthread_cond_signal(&qc);
        pthread_mutex_unlock(&qm);
        jitter(&s);
    }
    pthread_mutex_lock(&qm);
    pthread_cond_broadcast(&qc);
    pthread_mutex_unlock(&qm);
    return NULL;
}

// ----------------------------------------------------------------------------------------------------- driver

// The watchdog: every thread of a phase ticks as it goes; four seconds without one is a lost wake.
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
        if (++still >= 40) {
            printf("FAIL phase %s: no progress for 4 seconds after %ld steps: a wake was lost\n", phase_name, p);
            printf("SOME CHECKS FAILED\n");
            _exit(1);
        }
    }
}

static void report(const char* name, long long start) {
    printf("ok   %s (%lld ms)\n", name, (now_ns(CLOCK_MONOTONIC) - start) / 1000000);
}

int main(int argc, char** argv) {
    const char* only = argc > 1 ? argv[1] : NULL;
    setvbuf(stdout, NULL, _IONBF, 0);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = sig_noop;  // no SA_RESTART: interrupted waits return EINTR
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR1, &sa, NULL);
    sigaction(SIGUSR2, &sa, NULL);
    pthread_t wd;
    pthread_create(&wd, NULL, watchdog, NULL);

    long long t0;
    phase_name = "mailbox";
    if (only && !strstr("mailbox", only)) goto skip_mailbox;
    t0 = now_ns(CLOCK_MONOTONIC);
    run_mailbox(kPairs);
    join_mailbox(kPairs);
    report("mailbox", t0);
skip_mailbox:;

    phase_name = "barrier";
    if (only && !strstr("barrier", only)) goto skip_barrier;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t t[kBarrierThreads];
        for (int i = 0; i < kBarrierThreads; i++) pthread_create(&t[i], NULL, barrier_thread, (void*)(intptr_t)(i + 1));
        for (int i = 0; i < kBarrierThreads; i++) pthread_join(t[i], NULL);
    }
    report("barrier", t0);
skip_barrier:;

    phase_name = "timed";
    if (only && !strstr("timed", only)) goto skip_timed;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t t[kTimedThreads], w;
        pthread_create(&w, NULL, timed_waker, NULL);
        for (int i = 0; i < kTimedThreads; i++) pthread_create(&t[i], NULL, timed_thread, (void*)(intptr_t)(i + 1));
        for (int i = 0; i < kTimedThreads; i++) pthread_join(t[i], NULL);
        atomic_store(&timed_stop, 1);
        pthread_join(w, NULL);
    }
    report("timed", t0);
skip_timed:;

    phase_name = "signals";
    if (only && !strstr("signals", only)) goto skip_signals;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t f;
        atomic_store(&flood_on, 1);
        mailbox_rounds = 1500;
        run_mailbox(kPairs);
        pthread_create(&f, NULL, flooder, NULL);
        join_mailbox(kPairs);
        atomic_store(&flood_on, 0);
        pthread_join(f, NULL);
    }
    report("signals", t0);
skip_signals:;

    phase_name = "requeue";
    if (only && !strstr("requeue", only)) goto skip_requeue;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t t[kQueueWaiters], c;
        for (int i = 0; i < kQueueWaiters; i++) pthread_create(&t[i], NULL, queue_waiter, NULL);
        pthread_create(&c, NULL, queue_caster, NULL);
        pthread_join(c, NULL);
        for (int i = 0; i < kQueueWaiters; i++) pthread_join(t[i], NULL);
    }
    report("requeue", t0);
skip_requeue:;

    phase_name = "wakeop";
    if (only && !strstr("wakeop", only)) goto skip_wakeop;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t a, b, d;
        pthread_create(&a, NULL, op_waiter, &op_a);
        pthread_create(&b, NULL, op_waiter, &op_b);
        pthread_create(&d, NULL, op_driver, NULL);
        pthread_join(d, NULL);
        pthread_join(a, NULL);
        pthread_join(b, NULL);
    }
    report("wakeop", t0);
skip_wakeop:;

    phase_name = "churn";
    if (only && !strstr("churn", only)) goto skip_churn;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t p;
        pthread_create(&p, NULL, churn_parent, NULL);
        pthread_join(p, NULL);
    }
    report("churn", t0);
skip_churn:;

    phase_name = "pthread ring";
    if (only && !strstr("pthread ring", only)) goto skip_pthread_ring;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t t[kRing];
        for (int i = 0; i < kRing; i++) sem_init(&ring[i], 0, 0);
        for (int i = 0; i < kRing; i++) pthread_create(&t[i], NULL, ring_thread, (void*)(intptr_t)i);
        sem_post(&ring[0]);
        for (int i = 0; i < kRing; i++) pthread_join(t[i], NULL);
    }
    report("pthread ring", t0);
skip_pthread_ring:;

    phase_name = "pthread queue";
    if (only && !strstr("pthread queue", only)) goto skip_pthread_queue;
    t0 = now_ns(CLOCK_MONOTONIC);
    {
        pthread_t c[kConsumers], p[3];
        for (int i = 0; i < kConsumers; i++) pthread_create(&c[i], NULL, consumer, (void*)(intptr_t)i);
        for (int i = 0; i < 3; i++) pthread_create(&p[i], NULL, producer, (void*)(intptr_t)(i + 1));
        for (int i = 0; i < 3; i++) pthread_join(p[i], NULL);
        for (int i = 0; i < kConsumers; i++) pthread_join(c[i], NULL);
        if (consumed != kItems) {
            printf("FAIL pthread queue: %d of %d items consumed\n", consumed, kItems);
            atomic_fetch_add(&failures, 1);
        }
    }
    report("pthread queue", t0);
skip_pthread_queue:;

    if (atomic_load(&failures)) {
        printf("SOME CHECKS FAILED\n");
        return 1;
    }
    printf("ALL CHECKS PASSED\n");
    return 7;
}
