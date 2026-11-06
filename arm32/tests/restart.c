// What a signal handler does to the call it interrupts, as on Linux:
//   - with SA_RESTART a blocked read goes on after the handler;
//   - sleeps, polls and timed waits are never restarted (they return EINTR, or a timed wait keeps
//     its deadline), so a stream of signals cannot postpone them;
//   - sigtimedwait gives way to an unblocked signal outside its set (EINTR, the handler runs);
//   - a signal whose action is to ignore it is dropped when sent: it interrupts no call and does
//     not end sigsuspend.
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

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static atomic_int handled;
static void on_usr1(int sig) {
    (void)sig;
    atomic_fetch_add(&handled, 1);
}

static long now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

// Sends sig to the target every interval_ms for duration_ms, from a thread of its own.
struct Stream {
    pthread_t target;
    int sig, interval_ms, duration_ms;
    pthread_t thread;
};
static void* stream_main(void* arg) {
    struct Stream* s = arg;
    for (long end = now_ms() + s->duration_ms; now_ms() < end;) {
        usleep((useconds_t)s->interval_ms * 1000);
        pthread_kill(s->target, s->sig);
    }
    return NULL;
}
static void stream_start(struct Stream* s, int sig, int interval_ms, int duration_ms) {
    s->target = pthread_self();
    s->sig = sig;
    s->interval_ms = interval_ms;
    s->duration_ms = duration_ms;
    pthread_create(&s->thread, NULL, stream_main, s);
}
static void stream_end(struct Stream* s) { pthread_join(s->thread, NULL); }

// The pipe a reader blocks on, and a writer that fills it after a delay.
static int pipe_fds[2];
static void* write_later(void* arg) {
    usleep((useconds_t)(long)arg * 1000);
    char c = 'x';
    write(pipe_fds[1], &c, 1);
    return NULL;
}

static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t c = PTHREAD_COND_INITIALIZER;

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_usr1;
    sa.sa_flags = SA_RESTART;  // the calls Linux restarts are restarted; the others are not
    sigemptyset(&sa.sa_mask);
    sigaction(SIGUSR1, &sa, NULL);
    pipe(pipe_fds);

    // A read blocked on an empty pipe goes on through the handlers and returns the byte.
    {
        struct Stream s;
        int before = atomic_load(&handled);
        pthread_t w;
        pthread_create(&w, NULL, write_later, (void*)500L);
        stream_start(&s, SIGUSR1, 20, 300);
        char ch = 0;
        long n = read(pipe_fds[0], &ch, 1);
        stream_end(&s);
        pthread_join(w, NULL);
        CHECK("read restarted after handlers (SA_RESTART)", n == 1 && ch == 'x' && atomic_load(&handled) > before);
    }

    // Sleeps and polls return EINTR at the first handler instead of starting over: with a signal
    // every 30 ms for two seconds, a one-second call that restarted would end only after them.
    {
        struct Stream s;
        stream_start(&s, SIGUSR1, 30, 2000);
        struct timespec req = {1, 0}, rem = {0, 0};
        long t0 = now_ms();
        int r = nanosleep(&req, &rem);
        int e = errno;
        long took = now_ms() - t0;
        CHECK("nanosleep returns EINTR at a handler", r == -1 && e == EINTR && took < 800 && rem.tv_sec * 1000 + rem.tv_nsec / 1000000 > 100);

        t0 = now_ms();
        r = poll(NULL, 0, 1000);
        e = errno;
        took = now_ms() - t0;
        CHECK("poll returns EINTR at a handler", r == -1 && e == EINTR && took < 800);

        int ep = epoll_create1(0);
        struct epoll_event ev;
        t0 = now_ms();
        r = epoll_wait(ep, &ev, 1, 1000);
        e = errno;
        took = now_ms() - t0;
        close(ep);
        CHECK("epoll_wait returns EINTR at a handler", r == -1 && e == EINTR && took < 800);

        // A futex wait with a relative timeout, as the game's runtime makes them: Linux returns
        // EINTR at a handler; made again with the same arguments it would start over at each one.
        static int word = 0;
        struct timespec rel = {1, 0};
        t0 = now_ms();
        r = (int)syscall(__NR_futex, &word, FUTEX_WAIT_PRIVATE, 0, &rel, NULL, 0);
        e = errno;
        took = now_ms() - t0;
        CHECK("timed futex wait returns EINTR at a handler", r == -1 && e == EINTR && took < 800);

        // A timed condition wait keeps its deadline under handlers (this C library waits for an
        // absolute time, which comes back unchanged with a call made again).
        struct timespec deadline;
        clock_gettime(CLOCK_REALTIME, &deadline);
        deadline.tv_nsec += 400 * 1000000L;
        if (deadline.tv_nsec >= 1000000000L) {
            deadline.tv_sec += 1;
            deadline.tv_nsec -= 1000000000L;
        }
        t0 = now_ms();
        pthread_mutex_lock(&m);
        int tr = 0;
        while ((tr = pthread_cond_timedwait(&c, &m, &deadline)) == 0) {
        }
        pthread_mutex_unlock(&m);
        took = now_ms() - t0;
        stream_end(&s);
        printf("     (timed wait took %ld ms for 400)\n", took);
        CHECK("timed condition wait ends on schedule under handlers", tr == ETIMEDOUT && took < 1200);
    }

    // sigtimedwait for a blocked SIGUSR2 returns EINTR when the unblocked SIGUSR1 arrives, and the
    // handler of SIGUSR1 runs, rather than sleeping out its two seconds.
    {
        sigset_t set, old;
        sigemptyset(&set);
        sigaddset(&set, SIGUSR2);
        pthread_sigmask(SIG_BLOCK, &set, &old);
        struct Stream s;
        int before = atomic_load(&handled);
        stream_start(&s, SIGUSR1, 50, 60);
        // The system call takes the kernel's 64-bit signal set (sigtimedwait() itself needs API 23).
        unsigned long long set64 = 1ull << (SIGUSR2 - 1);
        struct timespec two = {2, 0};
        siginfo_t info;
        long t0 = now_ms();
        long r = syscall(__NR_rt_sigtimedwait, &set64, &info, &two, 8);
        int e = errno;
        long took = now_ms() - t0;
        stream_end(&s);
        pthread_sigmask(SIG_SETMASK, &old, NULL);
        CHECK("sigtimedwait gives way to an unblocked signal", r == -1 && e == EINTR && took < 1000 && atomic_load(&handled) > before);
    }

    // An ignored signal is dropped when it is sent: it does not cut a blocked read short ...
    {
        // Without SA_RESTART (signal() would add it), so an interrupted read would show as EINTR.
        struct sigaction ign;
        memset(&ign, 0, sizeof ign);
        ign.sa_handler = SIG_IGN;
        sigemptyset(&ign.sa_mask);
        sigaction(SIGUSR2, &ign, NULL);
        struct Stream s;
        pthread_t w;
        pthread_create(&w, NULL, write_later, (void*)300L);
        stream_start(&s, SIGUSR2, 20, 200);
        char ch = 0;
        long n = read(pipe_fds[0], &ch, 1);
        int e = errno;
        stream_end(&s);
        pthread_join(w, NULL);
        printf("     (read returned %ld, errno %d)\n", n, n < 0 ? e : 0);
        CHECK("an ignored signal does not interrupt a read", n == 1 && ch == 'x');
    }

    // ... and does not end sigsuspend, which returns only for the handled SIGUSR1 sent after it,
    // with the thread's mask as it was before.
    {
        sigset_t before_mask, after_mask, wait_mask;
        pthread_sigmask(SIG_SETMASK, NULL, &before_mask);
        sigfillset(&wait_mask);
        sigdelset(&wait_mask, SIGUSR1);
        sigdelset(&wait_mask, SIGUSR2);
        struct Stream ignored, handled_one;
        stream_start(&ignored, SIGUSR2, 10, 100);
        stream_start(&handled_one, SIGUSR1, 300, 300);
        long t0 = now_ms();
        sigsuspend(&wait_mask);
        long took = now_ms() - t0;
        stream_end(&ignored);
        stream_end(&handled_one);
        pthread_sigmask(SIG_SETMASK, NULL, &after_mask);
        printf("     (sigsuspend returned after %ld ms)\n", took);
        CHECK("an ignored signal does not end sigsuspend", took >= 250 && memcmp(&before_mask, &after_mask, sizeof before_mask) == 0);
    }

    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
