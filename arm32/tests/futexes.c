// Futex wake-ups are never lost: many threads wait and wake in the patterns the C library, the Java VM and the game's
// job system use, and a wake that does not reach a waiter that was about to sleep leaves it asleep for good.
// Ten phases, each with threads that sleep without a timeout (a lost wake hangs them) and a watchdog that
// fails the test when no thread made progress for a few seconds, instead of hanging it:
//   mailbox   pairs of threads handing a counter to each other, the waits plain and with bitsets, the wakes too
//   barrier   a generation barrier of eight threads, the last one to arrive wakes all the others
//   timed     waits with relative and absolute timeouts on both clocks, which must end in time, not early
//   signals   the mailbox again with signals (handlers without SA_RESTART, so waits return EINTR) at all its threads
//   requeue   a condition variable the way the C library of a desktop builds it: wake one, requeue the rest to the mutex
//   wakeop    FUTEX_WAKE_OP waking two words at once, its two 12-bit arguments read with their sign as the kernel reads them
//   edges     the kernel's answers at the edges of the wakes' arguments: FUTEX_WAKE_OP's operations and comparisons it
//             does not know (ENOSYS), counts of 0 and below (one woken), a bitset of 0 and requeue counts below 0 (EINVAL)
//   churn     batches of threads made, started with one wake and joined (the join is a futex wait too)
//   pthread   semaphores in a ring, a mutex and condition variables with and without timeouts
//   lostsignal  the handshake of a game's video decoder (seek and its worker): a signal that comes before the wait it was
//             meant for is lost, as a condition variable's is, and the worker's wait has to end on its own (a spurious
//             wake-up, which the standard allows a condition variable) for the worker to look at its flag again; it runs
//             only where a wait without a timeout ends by itself (the Windows layer), and says so where it is skipped
//
//   futexes [--waits-end-alone] [phase]
//
// --waits-end-alone is the runner's word that this host ends a wait without a timeout by itself (the Windows layer, every
// 100 ms): the lostsignal phase then runs whatever a look at the host would find, so that a layer that lost that end
// fails it (the watchdog's four seconds) where it would otherwise only be skipped. A phase's name runs that phase alone.
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
// What a phase without progress means, for the watchdog's line: a lost wake, except where the phase loses one on purpose.
static const char* volatile phase_stuck = "a wake was lost";
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
// The mailbox's threads that are through their rounds: the signals phase stops its flooder when all are, before it joins one.
static atomic_int mailbox_done;

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
    atomic_fetch_add(&mailbox_done, 1);
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
    atomic_fetch_add(&mailbox_done, 1);
    return NULL;
}

static pthread_t mailbox_threads[2 * kPairs];
static void run_mailbox(int pair_count) {
    memset(pairs, 0, sizeof pairs);
    atomic_store(&mailbox_done, 0);
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
        // op_b gets +1 (FUTEX_OP_ADD), and its waiter wakes when the old value of it is above 0xfff (FUTEX_OP_CMP_GT). The
        // kernel reads that 12-bit argument with its sign, as -1, which every count is above; read as 4095, it is above
        // every count, and that waiter would never wake.
        atomic_store(&op_a, i);
        unsigned enc = FUTEX_OP(FUTEX_OP_ADD, 1, FUTEX_OP_CMP_GT, 0xfff);
        long woke = futex_count(&op_a, FUTEX_WAKE_OP, 1, 1, &op_b, enc);
        // The ack of both waiters: a lost wake of either leaves this wait for good.
        unsigned cur;
        while ((cur = atomic_load(&op_ack)) < 2 * i) futex(&op_ack, FUTEX_WAIT, cur, NULL, NULL, 0);
        (void)woke;
    }
    return NULL;
}
// The operation's own argument has a sign too: ADD 0xfff takes one away, SET 0x800 makes the word -2048. Neither word has
// a waiter, so the call wakes nobody and returns 0.
static void op_arguments(void) {
    static word nobody, w;
    // 5 and one taken away.
    atomic_store(&w, 5);
    long n = futex_count(&nobody, FUTEX_WAKE_OP, 1, 1, &w, FUTEX_OP(FUTEX_OP_ADD, 0xfff, FUTEX_OP_CMP_EQ, 0));
    if (n != 0 || atomic_load(&w) != 4) {
        printf("FAIL wakeop: ADD 0xfff on 5 returned %ld and left %u, not 0 and 4\n", n, atomic_load(&w));
        atomic_fetch_add(&failures, 1);
    }
    // -2048 in all 32 bits.
    n = futex_count(&nobody, FUTEX_WAKE_OP, 1, 1, &w, FUTEX_OP(FUTEX_OP_SET, 0x800, FUTEX_OP_CMP_EQ, 0));
    if (n != 0 || atomic_load(&w) != 0xfffff800u) {
        printf("FAIL wakeop: SET 0x800 returned %ld and left 0x%08x, not 0 and 0xfffff800\n", n, atomic_load(&w));
        atomic_fetch_add(&failures, 1);
    }
}
// The comparison's argument on its own, where a wait that ends by itself cannot stand in for the wake: a word holding 0 is
// above 0xfff (-1), so the call wakes the word's sleeper. Read without its sign (4095) the comparison never holds, and on
// a host whose waits end on their own every so often the phase's stress would still pass, only slowly. The operation (ADD 0)
// leaves the word at 0, so the sleeper goes back to sleep after each wake; the call is made again until one wakes it,
// for two seconds at most (the first calls may come before it is asleep).
static word cmp_word;
static void* cmp_sleeper(void* arg) {
    (void)arg;
    unsigned cur;
    // Asleep for as long as the word holds 0: its end is the word's change below.
    while ((cur = atomic_load(&cmp_word)) == 0) futex(&cmp_word, FUTEX_WAIT, cur, NULL, NULL, 0);
    return NULL;
}
static void op_comparison(void) {
    static word nobody;
    pthread_t t;
    atomic_store(&cmp_word, 0);
    pthread_create(&t, NULL, cmp_sleeper, NULL);
    long n = 0;
    long long end = now_ns(CLOCK_MONOTONIC) + 2000000000LL;
    // The number woken on both words: nobody waits on the first, so 1 is the sleeper.
    while ((n = futex_count(&nobody, FUTEX_WAKE_OP, 1, 1, &cmp_word, FUTEX_OP(FUTEX_OP_ADD, 0, FUTEX_OP_CMP_GT, 0xfff))) == 0 &&
           now_ns(CLOCK_MONOTONIC) < end)
        usleep(1000);
    // The sleeper's end whatever the calls did: the word changes first, so that a wake it misses finds it awake.
    atomic_store(&cmp_word, 1);
    futex(&cmp_word, FUTEX_WAKE, INT_MAX, NULL, NULL, 0);
    pthread_join(t, NULL);
    if (n != 1) {
        printf("FAIL wakeop: a comparison above 0xfff woke %ld sleepers in two seconds, not 1\n", n);
        atomic_fetch_add(&failures, 1);
    }
}

// ----------------------------------------------------------------------------------------------------- edges

// A failed check of the edges phase: its line, and one more failure for the program's end.
static void edge_fail(const char* what, long got, int err) {
    printf("FAIL edges: %s (returned %ld, errno %d)\n", what, got, err);
    atomic_fetch_add(&failures, 1);
}

// FUTEX_WAKE_OP with an operation the kernel does not know (5 to 7, the shift flag or not): ENOSYS before the word is
// touched. With a comparison it does not know (6 to 15): the operation is done, then ENOSYS, as the kernel's
// futex_atomic_op_inuser does it. Neither wakes anybody (no count comes back). Nobody waits on these words.
static void edge_unknown_op_and_comparison(void) {
    static word nobody, w;
    for (unsigned op = 5; op <= 7; op++) {
        for (unsigned shift = 0; shift <= FUTEX_OP_OPARG_SHIFT; shift += FUTEX_OP_OPARG_SHIFT) {
            atomic_store(&w, 5);
            // A comparison that holds (the old value is 5): only the operation can make the call fail.
            long n = futex_count(&nobody, FUTEX_WAKE_OP, 1, 1, &w, FUTEX_OP(op | shift, 1, FUTEX_OP_CMP_EQ, 5));
            int e = errno;
            // The kernel's answer, and the word as it was.
            if (n != -1 || e != ENOSYS || atomic_load(&w) != 5) {
                char what[96];
                snprintf(what, sizeof what, "an operation the kernel does not know (%u%s) left 0x%x, not ENOSYS and 5", op,
                         shift ? " with the shift flag" : "", atomic_load(&w));
                edge_fail(what, n, e);
            }
        }
    }
    for (unsigned cmp = 6; cmp <= 15; cmp++) {
        atomic_store(&w, 5);
        // ADD 1 on 5: the kernel adds before it reads the comparison.
        long n = futex_count(&nobody, FUTEX_WAKE_OP, 1, 1, &w, FUTEX_OP(FUTEX_OP_ADD, 1, cmp, 5));
        int e = errno;
        if (n != -1 || e != ENOSYS || atomic_load(&w) != 6) {
            char what[96];
            snprintf(what, sizeof what, "a comparison the kernel does not know (%u) left 0x%x, not ENOSYS and 6", cmp,
                     atomic_load(&w));
            edge_fail(what, n, e);
        }
    }
}

// A word two sleepers wait on, for as long as it holds 0.
static word edge_word, edge_other;
static atomic_int edge_asleep;
static void* edge_sleeper(void* arg) {
    word* w = arg;
    atomic_fetch_add(&edge_asleep, 1);
    unsigned cur;
    // Back to sleep after any wake: only the word's change ends it.
    while ((cur = atomic_load(w)) == 0) futex(w, FUTEX_WAIT, cur, NULL, NULL, 0);
    return NULL;
}

// One wake call made with two threads asleep on `sleepers_on`, again until it wakes somebody, for two seconds at most (a
// sleeper whose wait ended by itself, on the Windows layer every 100 ms, is not in the wait for a moment); the number it
// said it woke, 0 if it never woke anybody. The sleepers' end after it whatever the calls did.
static long edge_wakes(word* sleepers_on, int op, unsigned val, long count, unsigned val3) {
    pthread_t t[2];
    atomic_store(&edge_word, 0);
    atomic_store(&edge_other, 0);
    atomic_store(&edge_asleep, 0);
    for (int i = 0; i < 2; i++) pthread_create(&t[i], NULL, edge_sleeper, sleepers_on);
    // Both in their loops; the first calls may still come before they sleep, and are made again.
    while (atomic_load(&edge_asleep) < 2) sched_yield();
    long n = 0;
    long long end = now_ns(CLOCK_MONOTONIC) + 2000000000LL;
    do {
        n = futex_count(&edge_word, op, val, count, &edge_other, val3);
        if (n != 0) break;
        // A step for the watchdog: these tries end by their own clock.
        tick();
        usleep(1000);
    } while (now_ns(CLOCK_MONOTONIC) < end);
    // Their end: the word changes first, so that a wake one of them misses finds it awake.
    atomic_store(sleepers_on, 1);
    futex(sleepers_on, FUTEX_WAKE, INT_MAX, NULL, NULL, 0);
    for (int i = 0; i < 2; i++) pthread_join(t[i], NULL);
    return n;
}

// A wake's count is a number with a sign, and one of 0 or below still wakes one waiter: the kernel's loop counts the
// waiter it woke before it compares with the count. Two sleepers, so that a count read as "all" shows too. For
// FUTEX_WAKE_OP both counts: the first word's, and the second word's when the comparison holds (ADD 0 on 0, EQ 0).
static void edge_counts(void) {
    static const struct { const char* what; int op; unsigned val; long count; unsigned val3; int second; } cases[] = {
        {"FUTEX_WAKE with a count of 0", FUTEX_WAKE, 0, 0, 0, 0},
        {"FUTEX_WAKE with a count of -1", FUTEX_WAKE, 0xffffffffu, 0, 0, 0},
        {"FUTEX_WAKE_BITSET with a count of 0", FUTEX_WAKE_BITSET, 0, 0, FUTEX_BITSET_MATCH_ANY, 0},
        {"FUTEX_WAKE_OP with a first count of 0", FUTEX_WAKE_OP, 0, 1, FUTEX_OP(FUTEX_OP_ADD, 0, FUTEX_OP_CMP_EQ, 1), 0},
        {"FUTEX_WAKE_OP with a first count of -1", FUTEX_WAKE_OP, 0xffffffffu, 1, FUTEX_OP(FUTEX_OP_ADD, 0, FUTEX_OP_CMP_EQ, 1), 0},
        {"FUTEX_WAKE_OP with a second count of 0", FUTEX_WAKE_OP, 1, 0, FUTEX_OP(FUTEX_OP_ADD, 0, FUTEX_OP_CMP_EQ, 0), 1},
        {"FUTEX_WAKE_OP with a second count of -1", FUTEX_WAKE_OP, 1, -1, FUTEX_OP(FUTEX_OP_ADD, 0, FUTEX_OP_CMP_EQ, 0), 1},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        long n = edge_wakes(cases[i].second ? &edge_other : &edge_word, cases[i].op, cases[i].val, cases[i].count, cases[i].val3);
        int e = errno;
        // One of the two sleepers, as the kernel wakes.
        if (n != 1) {
            char what[96];
            snprintf(what, sizeof what, "%s woke %ld of two sleepers, not 1", cases[i].what, n);
            edge_fail(what, n, e);
        }
    }
}

// What the kernel refuses before it wakes or moves anybody: a wake whose bitset is 0, which meets no waiter's, and a
// requeue with a count below 0 (looked at before FUTEX_CMP_REQUEUE's word is compared, so not EAGAIN). Nobody waits here.
static void edge_refused(void) {
    static word nobody, other;
    static const struct { const char* what; int op; unsigned val; long count; unsigned val3; } cases[] = {
        {"FUTEX_WAKE_BITSET with a bitset of 0", FUTEX_WAKE_BITSET, 1, 0, 0},
        {"FUTEX_REQUEUE waking -1", FUTEX_REQUEUE, 0xffffffffu, 1, 0},
        {"FUTEX_REQUEUE moving -1", FUTEX_REQUEUE, 1, -1, 0},
        {"FUTEX_CMP_REQUEUE moving -1", FUTEX_CMP_REQUEUE, 1, -1, 0},
        {"FUTEX_CMP_REQUEUE waking -1 with a word that differs", FUTEX_CMP_REQUEUE, 0xffffffffu, 1, 7},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        atomic_store(&nobody, 0);
        long n = futex_count(&nobody, cases[i].op, cases[i].val, cases[i].count, &other, cases[i].val3);
        int e = errno;
        if (n != -1 || e != EINVAL) {
            char what[96];
            snprintf(what, sizeof what, "%s, not refused with EINVAL", cases[i].what);
            edge_fail(what, n, e);
        }
    }
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

// ----------------------------------------------------------------------------------------------------- lostsignal

// The game's video decoder keeps a request flag that its worker reads before it takes the queue's mutex,
// and waits on the queue's condition variable when the queue says so, without reading the flag again. A seek that sets the
// flag and signals the queue in between finds nobody waiting: its signal is gone, the worker then waits for a wake that
// never comes, and the seek waits for the worker's answer. On a phone the window is a few instructions; here it is as
// long as the first run of the worker's code takes. The worker's wait must come back by itself for the loop to see the flag.
enum { kLostRounds = 20 };
static pthread_mutex_t lq_m = PTHREAD_MUTEX_INITIALIZER, lr_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t lq_c = PTHREAD_COND_INITIALIZER, lr_c = PTHREAD_COND_INITIALIZER;
static atomic_int lost_flag, lost_in_window, lost_acked, lost_stop, lost_done;
static void* lost_worker(void* arg) {
    (void)arg;
    for (;;) {
        if (atomic_load(&lost_stop)) {
            atomic_store(&lost_done, 1);
            return NULL;
        }
        if (atomic_load(&lost_flag)) {
            // The answer to the request.
            pthread_mutex_lock(&lr_m);
            atomic_store(&lost_flag, 0);
            atomic_store(&lost_acked, 1);
            pthread_cond_signal(&lr_c);
            pthread_mutex_unlock(&lr_m);
            continue;
        }
        // The window between reading the flag and taking the mutex.
        atomic_store(&lost_in_window, 1);
        usleep(5000);
        pthread_mutex_lock(&lq_m);
        pthread_cond_wait(&lq_c, &lq_m);  // the queue is empty: wait, as the decoder does, without looking at the flag
        pthread_mutex_unlock(&lq_m);
        tick();
    }
}
static void run_lostsignal(void) {
    pthread_t w;
    pthread_create(&w, NULL, lost_worker, NULL);
    for (int i = 0; i < kLostRounds; i++) {
        while (!atomic_load(&lost_in_window)) sched_yield();
        atomic_store(&lost_in_window, 0);
        // The seek: the flag, the signal to the queue (nobody waits yet), then the wait for the answer.
        atomic_store(&lost_flag, 1);
        pthread_mutex_lock(&lq_m);
        pthread_cond_signal(&lq_c);
        pthread_mutex_unlock(&lq_m);
        pthread_mutex_lock(&lr_m);
        while (!atomic_load(&lost_acked)) pthread_cond_wait(&lr_c, &lr_m);
        atomic_store(&lost_acked, 0);
        pthread_mutex_unlock(&lr_m);
        tick();
    }
    atomic_store(&lost_stop, 1);
    // The worker may be asleep in its wait: signals until it has seen the stop.
    while (!atomic_load(&lost_done)) {
        pthread_mutex_lock(&lq_m);
        pthread_cond_signal(&lq_c);
        pthread_mutex_unlock(&lq_m);
        usleep(2000);
    }
    pthread_join(w, NULL);
}
// Whether a futex wait without a timeout ends here by itself, which the phase needs: the Windows layer ends one every
// 100 ms. The Linux kernel never does, on a phone and under the runtime on a Linux host, which passes the wait on to it:
// there a wait ends only with a wake, as the game's own code has it on a phone, and the phase is skipped. A wait on a word
// that only a helper wakes, a second later, finds out: back before the helper with 0, it ended by itself.
static word alone_word;
static atomic_int alone_woken;
static void* alone_helper(void* arg) {
    (void)arg;
    usleep(1000000);
    // Noted before the wake, so that a wait it ends cannot pass for one that ended by itself.
    atomic_store(&alone_woken, 1);
    // The word changes first, so that a wait that starts late does not sleep for good.
    atomic_store(&alone_word, 1);
    futex(&alone_word, FUTEX_WAKE, INT_MAX, NULL, NULL, 0);
    return NULL;
}
static int waits_end_by_themselves(void) {
    pthread_t t;
    pthread_create(&t, NULL, alone_helper, NULL);
    long r;
    // A signal's interruption (EINTR) is no end by itself: the wait goes on.
    do r = futex(&alone_word, FUTEX_WAIT, 0, NULL, NULL, 0);
    while (r == -1 && errno == EINTR);
    int by_itself = r == 0 && !atomic_load(&alone_woken);
    pthread_join(t, NULL);
    return by_itself;
}

// ----------------------------------------------------------------------------------------------------- driver

// The watchdog: every thread of a phase ticks as it goes; four seconds without one is a lost wake. The seconds are the
// monotonic clock's, not a count of its sleeps: a signal for the process can land on this thread and end a sleep early,
// and forty short sleeps made a few milliseconds without a tick look like four seconds.
static void* watchdog(void* arg) {
    (void)arg;
    long last = -1;
    long long since = now_ns(CLOCK_MONOTONIC);
    for (;;) {
        usleep(100000);
        long p = atomic_load(&progress);
        long long now = now_ns(CLOCK_MONOTONIC);
        // A tick since the last look: the four seconds start again.
        if (p != last) {
            last = p;
            since = now;
            continue;
        }
        if (now - since >= 4000000000LL) {
            printf("FAIL phase %s: no progress for 4 seconds after %ld steps: %s\n", phase_name, p, phase_stuck);
            printf("SOME CHECKS FAILED\n");
            _exit(1);
        }
    }
}

static void report(const char* name, long long start) {
    printf("ok   %s (%lld ms)\n", name, (now_ns(CLOCK_MONOTONIC) - start) / 1000000);
}

int main(int argc, char** argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    // The runner's word that waits end by themselves here (see the top of this file), then a phase's name, both optional.
    int waits_end_alone = 0;
    const char* only = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--waits-end-alone") == 0) {
            waits_end_alone = 1;
        } else if (argv[i][0] == '-' || only) {
            // An option this program does not know, or a second phase: taken for a phase's name, it would run no phase
            // at all and pass.
            printf("FAIL: futexes takes --waits-end-alone and one phase's name, not %s\n", argv[i]);
            printf("SOME CHECKS FAILED\n");
            return 1;
        } else {
            only = argv[i];
        }
    }
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
        mailbox_rounds = 800;
        run_mailbox(kPairs);
        pthread_create(&f, NULL, flooder, NULL);
        // The flooder names the threads by their pthread_t, which is a thread only until it is joined: the join frees it,
        // and a pthread_kill on it reads freed memory. The flooder stops once every thread is through its rounds, before
        // the first join; one that has ended by then is still there to name (its ID is 0 then, which the kernel refuses).
        while (atomic_load(&mailbox_done) < 2 * kPairs) usleep(1000);
        atomic_store(&flood_on, 0);
        pthread_join(f, NULL);
        join_mailbox(kPairs);
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
    // The operation's argument first, on words nobody waits on, then the comparison's with one sleeper; then the stress.
    op_arguments();
    op_comparison();
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

    phase_name = "edges";
    if (only && !strstr("edges", only)) goto skip_edges;
    t0 = now_ns(CLOCK_MONOTONIC);
    // What the kernel refuses first (nothing to wait for), then the counts, each with two sleepers.
    edge_unknown_op_and_comparison();
    edge_refused();
    edge_counts();
    report("edges", t0);
skip_edges:;

    phase_name = "lostsignal";
    if (only && !strstr("lostsignal", only)) goto skip_lostsignal;
    t0 = now_ns(CLOCK_MONOTONIC);
    // Only where a wait ends by itself; elsewhere the line says why the phase does not run, and the program goes on. Where
    // the runner says waits end by themselves here, the phase runs without the look: one that never ends is then the
    // watchdog's failure, not a skip (a look that a loaded machine kept waiting past its second would say no too).
    if (!waits_end_alone && !waits_end_by_themselves()) {
        printf("skip lostsignal: a wait without a timeout ends here only with a wake, as on the Linux kernel, and this "
               "phase needs one that ends by itself\n");
        goto skip_lostsignal;
    }
    // The phase loses its signal on purpose: stuck, it is the worker's wait that never ended by itself (a wait without a
    // timeout on the Linux kernel ends only with a wake; the Windows layer ends one every 100 ms).
    phase_stuck = "the worker's wait did not end on its own";
    run_lostsignal();
    phase_stuck = "a wake was lost";
    report("lostsignal", t0);
skip_lostsignal:;

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
