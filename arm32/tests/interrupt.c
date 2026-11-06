// Signals interrupting blocking system calls: a thread blocks again and again in read, futex,
// epoll_wait, poll and nanosleep, and every signal sent to it must run its handler, also the ones
// that arrive just as it enters a call (a lost one leaves it blocked with the signal pending).
#include <errno.h>
#include <linux/futex.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

enum { kRounds = 400 };

static atomic_int handled, interrupted, stop;
static int pipe_fds[2], epoll_fd;
static int futex_word;

static void on_signal(int sig) {
    (void)sig;
    atomic_fetch_add(&handled, 1);
}

// Blocks in one call after another; counts the calls that came back with EINTR.
static void* blocker(void* arg) {
    (void)arg;
    char c;
    struct epoll_event ev;
    struct pollfd pfd = {pipe_fds[0], POLLIN, 0};
    struct timespec long_sleep = {60, 0};
    for (int i = 0; !atomic_load(&stop); i++) {
        long r;
        switch (i % 5) {
        case 0: r = read(pipe_fds[0], &c, 1); break;
        case 1: r = syscall(SYS_futex, &futex_word, FUTEX_WAIT_PRIVATE, 0, NULL, NULL, 0); break;
        case 2: r = epoll_wait(epoll_fd, &ev, 1, -1); break;
        case 3: r = poll(&pfd, 1, -1); break;
        default: r = nanosleep(&long_sleep, NULL); break;
        }
        if (r < 0 && errno == EINTR) atomic_fetch_add(&interrupted, 1);
    }
    return NULL;
}

// Waits up to two seconds for the counter to reach want: spinning first, so the next signal
// leaves while the blocker is on its way into its next call.
static int wait_for(atomic_int* counter, int want) {
    for (int i = 0; i < 100000; i++) {
        if (atomic_load(counter) >= want) return 1;
    }
    for (int i = 0; i < 2000; i++) {
        if (atomic_load(counter) >= want) return 1;
        usleep(1000);
    }
    return 0;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;  // no SA_RESTART: interrupted calls return EINTR
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR1, &sa, NULL);
    pipe(pipe_fds);
    epoll_fd = epoll_create1(0);
    struct epoll_event ev = {EPOLLIN, {.fd = pipe_fds[0]}};
    epoll_ctl(epoll_fd, EPOLL_CTL_ADD, pipe_fds[0], &ev);
    pthread_t t;
    pthread_create(&t, NULL, blocker, NULL);
    int failures = 0;
    for (int i = 1; i <= kRounds; i++) {
        // Every other one leaves as soon as the last was handled, while the blocker is on its way
        // into its next call (or still in the handler); the others once it surely blocks.
        if (i % 2) usleep(2000);
        pthread_kill(t, SIGUSR1);
        if (!wait_for(&handled, i)) {
            printf("FAIL round %d: the signal was not handled (handled %d, calls interrupted %d)\n", i,
                   atomic_load(&handled), atomic_load(&interrupted));
            failures++;
            break;
        }
    }
    // The delayed half find the thread blocked.
    if (!failures && atomic_load(&interrupted) < kRounds / 4) {
        printf("FAIL only %d of %d signals interrupted a call\n", atomic_load(&interrupted), kRounds);
        failures++;
    }
    if (!failures) printf("ok   %d signals handled, %d of them ending a blocked call\n", kRounds, atomic_load(&interrupted));
    // Let the blocker go: one more signal ends its last call.
    atomic_store(&stop, 1);
    pthread_kill(t, SIGUSR1);
    pthread_join(t, NULL);
    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
