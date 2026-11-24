// Guest signals: a handler on the same thread, a handler on another thread blocked in a futex,
// floats surviving a handler, a thread ID that names no thread, a thread of another thread group,
// and the suspend/resume handshake Boehm GC uses to stop threads.
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <semaphore.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static volatile int self_hits = 0;
static volatile pid_t handler_tid = 0;
static void on_usr1(int sig, siginfo_t* info, void* uc) { (void)info; (void)uc; self_hits += sig == SIGUSR1; handler_tid = (pid_t)syscall(__NR_gettid); }

// Boehm-style stop: the suspend handler acknowledges, then sleeps in sigsuspend until the world
// is no longer stopped, checking the shared flag again after every wake-up.
static sem_t ack;
static volatile int resumed = 0;
static volatile int world_stopped = 0;
static void on_suspend(int sig) {
    (void)sig;
    sigset_t wait_mask;
    sigfillset(&wait_mask);
    sigdelset(&wait_mask, SIGUSR2);
    sem_post(&ack);
    while (world_stopped) sigsuspend(&wait_mask);
    sem_post(&ack);
}
static void on_resume(int sig) { (void)sig; resumed++; }

// A handler that stores the value an interrupted LDREX read back into the word: Linux clears the
// exclusive monitor on every return from an exception, so the STREX after the handler must fail
// even though the word holds the value LDREX saw.
static volatile unsigned exclusive_word = 5;
static void on_alarm(int sig) {
    (void)sig;
    exclusive_word = 5;
}

static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t c = PTHREAD_COND_INITIALIZER;
static volatile int stop = 0;
static volatile pid_t worker_tid = 0;
static volatile double worker_float = 0;

static void* worker(void* arg) {
    (void)arg;
    worker_tid = (pid_t)syscall(__NR_gettid);
    double x = 1.25;
    pthread_mutex_lock(&m);
    while (!stop) pthread_cond_wait(&c, &m);  // blocked in a futex while being signalled
    pthread_mutex_unlock(&m);
    worker_float = x * 2;
    return NULL;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_usr1;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigaction(SIGUSR1, &sa, NULL);
    raise(SIGUSR1);
    CHECK("handler on the same thread", self_hits == 1 && handler_tid == (pid_t)syscall(__NR_gettid));

    volatile double f = 3.5;
    raise(SIGUSR1);
    CHECK("floats survive a handler", f * 2 == 7.0 && self_hits == 2);

    // A thread ID of 0 or below names no thread: tgkill and tkill refuse it (EINVAL) and send
    // nothing. The C library passes 0 on for a thread that has ended and is not joined yet, and
    // that signal must not go to another thread of the process instead (here the only one).
    int hits_before = self_hits;
    long r0 = syscall(__NR_tgkill, getpid(), 0, SIGUSR1);
    int e0 = errno;
    long r1 = syscall(__NR_tkill, 0, SIGUSR1);
    int e1 = errno;
    long r2 = syscall(__NR_tgkill, getpid(), -1, SIGUSR1);
    int e2 = errno;
    // A signal sent to the process anyway would have reached this thread by now.
    usleep(20000);
    CHECK("a thread ID of 0 or below names no thread",
          r0 == -1 && e0 == EINVAL && r1 == -1 && e1 == EINVAL && r2 == -1 && e2 == EINVAL && self_hits == hits_before);
    // The checks below count the handler's runs from here, whatever this one found.
    self_hits = hits_before;

    // A thread named with another thread group's ID is none of this process's: tgkill answers ESRCH and sends nothing,
    // for the signal 0 too. A thread there is not is ESRCH whatever the signal, as the kernel looks for the thread before
    // the signal; a signal there is not, to a thread there is, EINVAL. INT_MAX is above every ID Linux hands out (4,194,304
    // at most). The process names itself by getpid(), for tgkill and kill alike, as the C library's raise() and
    // pthread_kill() do: these must still work.
    long me = syscall(__NR_gettid);
    long g0 = syscall(__NR_tgkill, INT_MAX, me, 0);
    int ge0 = errno;
    long g1 = syscall(__NR_tgkill, INT_MAX, me, SIGUSR1);
    int ge1 = errno;
    long g2 = syscall(__NR_tkill, INT_MAX, 65);
    int ge2 = errno;
    long g3 = syscall(__NR_tgkill, getpid(), INT_MAX, 65);
    int ge3 = errno;
    long g4 = syscall(__NR_tgkill, getpid(), me, 65);
    int ge4 = errno;
    long g5 = syscall(__NR_tgkill, getpid(), me, 0);
    int g6 = kill(getpid(), 0);
    // A signal that went anyway would have reached this thread by now.
    usleep(20000);
    CHECK("a thread of another thread group is none of this one's",
          g0 == -1 && ge0 == ESRCH && g1 == -1 && ge1 == ESRCH && self_hits == hits_before);
    CHECK("a thread there is not before a signal there is not",
          g2 == -1 && ge2 == ESRCH && g3 == -1 && ge3 == ESRCH && g4 == -1 && ge4 == EINVAL);
    CHECK("this process by its own ID", g5 == 0 && g6 == 0);
    self_hits = hits_before;

    struct sigaction alarm_action;
    memset(&alarm_action, 0, sizeof alarm_action);
    alarm_action.sa_handler = on_alarm;
    sigaction(SIGALRM, &alarm_action, NULL);
    // Only the bare system call between LDREX and STREX: raise() takes the C library's thread
    // list lock, whose own LDREX/STREX would end the reservation whatever the handler does.
    long pid = getpid(), tid = syscall(__NR_gettid);
    unsigned seen, status;
    __asm__ volatile("ldrex %0, [%1]" : "=r"(seen) : "r"(&exclusive_word) : "memory");
    syscall(__NR_tgkill, pid, tid, SIGALRM);  // the handler runs on the way out of the call
    __asm__ volatile("strex %0, %2, [%1]" : "=&r"(status) : "r"(&exclusive_word), "r"(seen + 1) : "memory");
    CHECK("store-exclusive fails after a signal handler", seen == 5 && status == 1 && exclusive_word == 5);

    pthread_t t;
    pthread_create(&t, NULL, worker, NULL);
    while (!worker_tid) usleep(1000);
    usleep(50000);
    pthread_kill(t, SIGUSR1);
    for (int i = 0; i < 200 && self_hits < 3; i++) usleep(5000);
    CHECK("handler on a thread blocked in a futex", self_hits == 3 && handler_tid == worker_tid);

    sem_init(&ack, 0, 0);
    struct sigaction s1, s2;
    memset(&s1, 0, sizeof s1);
    memset(&s2, 0, sizeof s2);
    s1.sa_handler = on_suspend;
    s1.sa_flags = SA_RESTART;
    // As in Boehm: everything, the resume signal included, is blocked while the handler runs, so
    // the resume signal can only arrive inside sigsuspend, which unblocks it atomically.
    sigfillset(&s1.sa_mask);
    s2.sa_handler = on_resume;
    s2.sa_flags = SA_RESTART;
    sigaction(SIGPWR, &s1, NULL);
    sigaction(SIGUSR2, &s2, NULL);
    world_stopped = 1;
    pthread_kill(t, SIGPWR);
    sem_wait(&ack);  // the worker is stopped now
    world_stopped = 0;
    pthread_kill(t, SIGUSR2);
    sem_wait(&ack);  // and running again
    // The resume handler runs inside sigsuspend, or right after the suspend handler when the
    // world was restarted before the worker got there; either way exactly once.
    for (int i = 0; i < 400 && resumed < 1; i++) usleep(5000);
    usleep(20000);
    CHECK("suspend and resume handshake", resumed == 1);

    pthread_mutex_lock(&m);
    stop = 1;
    pthread_cond_broadcast(&c);
    pthread_mutex_unlock(&m);
    pthread_join(t, NULL);
    CHECK("worker finished with its float intact", worker_float == 2.5);
    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
