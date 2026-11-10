// Futex wakes are never lost to signals. Two threads ping-pong through two semaphores while the
// main thread keeps signalling one of them, the poster, with two kinds of signal:
//   - SIGUSR1, handled without SA_RESTART: a signal that is ready when the poster wakes the other
//     thread must not cancel the wake (Linux never returns EINTR from FUTEX_WAKE, and the C
//     library ignores what it returns);
//   - SIGUSR2, which the poster blocks: it is never delivered, it only makes the runtime interrupt
//     the poster's host thread, and that interrupt must not cancel a wake either.
// sem_post issues the futex wake only when the other side sleeps, and a wake that never reaches it
// leaves it asleep for good: the rounds stop moving.
// The signals come for the first 20 seconds: how many rounds a flood lets through varies a lot from one
// run to the next (from 1 to 70 seconds for all of them on one PC), and the rounds left finish without
// it, so a run takes about as long on any machine. Progress is printed every 5 seconds, so that a run a
// time limit stops still says how far it got.
#include <errno.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

enum { kRounds = 4000, kFloodMs = 20000, kProgressMs = 5000 };

static sem_t ping, pong;
static atomic_int rounds, handled;

static void on_signal(int sig) {
    (void)sig;
    atomic_fetch_add(&handled, 1);
}

// sem_wait reports a signal that cut it short (EINTR) to programs built for newer API levels.
static void wait_sem(sem_t* s) {
    while (sem_wait(s) != 0 && errno == EINTR) {
    }
}

// The signalled side: each sem_post here finds the other thread asleep in sem_wait and wakes it.
static void* poster(void* arg) {
    (void)arg;
    // SIGUSR2 stays blocked here: sending it only produces the runtime's host interrupt.
    sigset_t block;
    sigemptyset(&block);
    sigaddset(&block, SIGUSR2);
    pthread_sigmask(SIG_BLOCK, &block, NULL);
    for (int i = 0; i < kRounds; i++) {
        sem_post(&ping);
        wait_sem(&pong);
    }
    return NULL;
}

// Never signalled: an interrupted wait here cannot make up for a wake that did not arrive.
static void* waiter(void* arg) {
    (void)arg;
    for (int i = 0; i < kRounds; i++) {
        wait_sem(&ping);
        atomic_fetch_add(&rounds, 1);
        sem_post(&pong);
    }
    return NULL;
}

static long ms_since(const struct timespec* t) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (now.tv_sec - t->tv_sec) * 1000 + (now.tv_nsec - t->tv_nsec) / 1000000;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;  // no SA_RESTART: interrupted waits return EINTR
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR1, &sa, NULL);
    sigaction(SIGUSR2, &sa, NULL);
    sem_init(&ping, 0, 0);
    sem_init(&pong, 0, 0);
    pthread_t w, p;
    pthread_create(&w, NULL, waiter, NULL);
    pthread_create(&p, NULL, poster, NULL);
    // Signal the poster as fast as possible, alternating the two kinds, until every round is done
    // or the rounds stop moving for three seconds.
    int last = -1, sent = 0;
    struct timespec moved, began, said;
    clock_gettime(CLOCK_MONOTONIC, &moved);
    began = said = moved;
    for (;;) {
        int r = atomic_load(&rounds);
        if (r >= kRounds) break;
        if (r != last) {
            last = r;
            clock_gettime(CLOCK_MONOTONIC, &moved);
        } else if (ms_since(&moved) > 3000) {
            printf("FAIL rounds stopped at %d of %d after %d signals (%d handled): a wake was lost\n", r, kRounds, sent,
                   atomic_load(&handled));
            printf("SOME CHECKS FAILED\n");
            // The two threads sleep for good; exit without joining them.
            _exit(1);
        }
        if (ms_since(&said) > kProgressMs) {
            printf("     %d rounds, %d signals\n", r, sent);
            clock_gettime(CLOCK_MONOTONIC, &said);
        }
        if (ms_since(&began) < kFloodMs) pthread_kill(p, (sent++ & 1) ? SIGUSR2 : SIGUSR1);
    }
    pthread_join(p, NULL);
    pthread_join(w, NULL);
    printf("ok   %d rounds with %d signals sent to the waking thread (%d handled)\n", kRounds, sent, atomic_load(&handled));
    printf("ALL CHECKS PASSED\n");
    return 7;
}
