// Descriptors and the waits on them, as Linux has them: on a phone and on a Linux desktop the kernel answers, on Windows
// the runtime's own layer (arm32/src/win), which must answer the same. A poll that ends at its deadline while it is
// woken over and over, a poll on a quiet socket that sleeps, the bytes waiting (FIONREAD), SO_LINGER read back, refused
// connects, epoll's list changed while a thread waits on it, an epoll entry for a number closed and opened again,
// edge-triggered entries, an epoll inside another and a loop of them, a close while an epoll waits, two readers of one
// pipe, readv on a pipe and a read of nothing, appends from two descriptors at once, and a directory listed again from
// its start and from a place in it. Prints one line per check.
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static long ms_since(const struct timespec* t0) {
    struct timespec t1;
    clock_gettime(CLOCK_MONOTONIC, &t1);
    return (t1.tv_sec - t0->tv_sec) * 1000 + (t1.tv_nsec - t0->tv_nsec) / 1000000;
}

// What the program does now, for the watchdog to name: a wait that never ends is a failure too.
static const char* volatile step = "starting";
static void* watchdog(void* arg) {
    (void)arg;
    sleep(60);
    printf("FAIL still at \"%s\" after a minute\nSOME CHECKS FAILED\n", step);
    _exit(1);
}

// The CPU time this thread has used, in milliseconds: a wait that spins uses it, one that sleeps does not.
static long thread_cpu_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t);
    return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

// A pipe written and read back over and over by another thread: every read tells the write end's waiters that there
// is room, every write the read end's that there is something.
static atomic_int churn_stop;
static int churn_pipe[2];
static void* churn(void* arg) {
    (void)arg;
    char c = 'x';
    while (!atomic_load(&churn_stop)) {
        if (write(churn_pipe[1], &c, 1) != 1 || read(churn_pipe[0], &c, 1) != 1) break;
    }
    return NULL;
}

// The loopback address with `port` (0: any).
static struct sockaddr_in loopback(unsigned short port) {
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    sa.sin_port = htons(port);
    return sa;
}

// A listening TCP socket on the loopback, and its address.
static int listener(struct sockaddr_in* where) {
    int l = socket(AF_INET, SOCK_STREAM, 0);
    *where = loopback(0);
    socklen_t len = sizeof *where;
    if (l < 0 || bind(l, (struct sockaddr*)where, sizeof *where) != 0 || listen(l, 4) != 0 || getsockname(l, (struct sockaddr*)where, &len) != 0) return -1;
    return l;
}

// What a thread waiting on an epoll got, and when.
static int ep_wait_fd, ep_waited;
static long ep_waited_ms;
static void* epoll_waiter(void* arg) {
    (void)arg;
    struct epoll_event ev;
    struct timespec t0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    ep_waited = epoll_wait(ep_wait_fd, &ev, 1, 3000);
    ep_waited_ms = ms_since(&t0);
    return NULL;
}

// A write that comes late, after a read should have returned.
static int late_fd;
static void* write_late(void* arg) {
    (void)arg;
    usleep(1500000);
    if (write(late_fd, "LATE", 4) != 4) return NULL;
    return NULL;
}

// A wait on an epoll that nothing will wake for three seconds, holding what the epoll watches as it waits.
static int sleeper_ep;
static void* epoll_sleeper(void* arg) {
    (void)arg;
    struct epoll_event ev;
    epoll_wait(sleeper_ep, &ev, 1, 3000);
    return NULL;
}

// A read of one byte, and what it returned.
static int reader_fd;
static ssize_t reader_got[2];
static void* one_byte_reader(void* arg) {
    char c;
    reader_got[(intptr_t)arg] = read(reader_fd, &c, 1);
    return NULL;
}

// Records of eight bytes of one letter, appended through a descriptor of its own.
static const char* kAppendPath = "descriptors.tmp";
enum { kRecords = 2000, kRecord = 8 };
static void* appender(void* arg) {
    int fd = open(kAppendPath, O_WRONLY | O_APPEND | O_CLOEXEC);
    char rec[kRecord];
    memset(rec, (int)(intptr_t)arg, sizeof rec);
    for (int i = 0; i < kRecords && fd >= 0; ++i)
        if (write(fd, rec, sizeof rec) != (ssize_t)sizeof rec) break;
    if (fd >= 0) close(fd);
    return NULL;
}

// A directory entry as getdents64 gives it.
struct dirent64_record {
    uint64_t d_ino;
    int64_t d_off;
    unsigned short d_reclen;
    unsigned char d_type;
    char d_name[];
};

// The names getdents64 gives from where the descriptor is, in one string; `first_off` the place after the first.
static void list_records(int fd, char* out, size_t size, int64_t* first_off) {
    char buf[4096];
    out[0] = '\0';
    for (long len; (len = syscall(__NR_getdents64, fd, buf, sizeof buf)) > 0;) {
        for (long at = 0; at < len;) {
            const struct dirent64_record* e = (const struct dirent64_record*)(buf + at);
            if (first_off && at == 0 && out[0] == '\0') *first_off = e->d_off;
            strncat(out, e->d_name, size - strlen(out) - 1);
            strncat(out, "/", size - strlen(out) - 1);
            at += e->d_reclen;
        }
    }
}

// The names in a directory stream from where it is to its end, in one string.
static void list_rest(DIR* d, char* out, size_t size) {
    out[0] = '\0';
    for (struct dirent* e; (e = readdir(d)) != NULL;) {
        strncat(out, e->d_name, size - strlen(out) - 1);
        strncat(out, "/", size - strlen(out) - 1);
    }
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    struct timespec t0;
    pthread_t t, dog;
    pthread_create(&dog, NULL, watchdog, NULL);

    // A write end is never readable: a poll for that is woken by every read of the pipe, and ends at its deadline all
    // the same.
    if (pipe(churn_pipe) != 0) return 1;
    pthread_create(&t, NULL, churn, NULL);
    step = "a poll woken over and over";
    struct pollfd pf = {churn_pipe[1], POLLIN, 0};
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int r = poll(&pf, 1, 200);
    long ms = ms_since(&t0);
    atomic_store(&churn_stop, 1);
    pthread_join(t, NULL);
    CHECK("poll ends at its deadline while it is woken over and over", r == 0 && ms >= 150 && ms < 2000);
    close(churn_pipe[0]);
    close(churn_pipe[1]);

    // A connected pair on the loopback.
    struct sockaddr_in where;
    int l = listener(&where);
    step = "a connect on the loopback";
    int a = socket(AF_INET, SOCK_STREAM, 0);
    int connected = l >= 0 && a >= 0 && connect(a, (struct sockaddr*)&where, sizeof where) == 0;
    int b = connected ? accept(l, NULL, NULL) : -1;
    CHECK("a TCP connection on the loopback", connected && b >= 0);
    if (l >= 0) close(l);

    // Nothing to read on the accepted end: a poll for it sleeps to its deadline. Its network events so far (Windows
    // says it is writable when it is set up) are no reason to look again and again.
    step = "a poll on a quiet socket";
    struct pollfd sp = {b, POLLIN, 0};
    long cpu0 = thread_cpu_ms();
    clock_gettime(CLOCK_MONOTONIC, &t0);
    r = poll(&sp, 1, 300);
    ms = ms_since(&t0);
    long cpu = thread_cpu_ms() - cpu0;
    CHECK("poll on a quiet socket sleeps until its deadline", r == 0 && ms >= 250 && cpu < 100);
    if (r != 0 || cpu >= 100) printf("     poll %d after %ld ms, %ld ms of CPU\n", r, ms, cpu);

    // Five bytes sent: the poll sees them, and FIONREAD counts them.
    step = "a poll on a socket with data";
    send(a, "hello", 5, 0);
    r = poll(&sp, 1, 2000);
    int waiting = -1;
    ioctl(b, FIONREAD, &waiting);
    CHECK("poll sees a socket's data, and FIONREAD its bytes", r == 1 && (sp.revents & POLLIN) && waiting == 5);
    char got5[8];
    CHECK("the bytes read", recv(b, got5, sizeof got5, 0) == 5 && memcmp(got5, "hello", 5) == 0);

    // Linux's linger is two ints.
    struct linger lg = {1, 5}, back = {0, 0};
    socklen_t lglen = sizeof back;
    r = setsockopt(a, SOL_SOCKET, SO_LINGER, &lg, sizeof lg);
    int r2 = getsockopt(a, SOL_SOCKET, SO_LINGER, &back, &lglen);
    CHECK("SO_LINGER reads back as it was set", r == 0 && r2 == 0 && back.l_onoff == 1 && back.l_linger == 5 && lglen == sizeof back);
    struct linger off = {0, 0};
    setsockopt(a, SOL_SOCKET, SO_LINGER, &off, sizeof off);

    // The receive timeout reads back as it was set.
    step = "a read past SO_RCVTIMEO";
    struct timeval tv = {0, 250000}, tvb = {0, 0};
    socklen_t tvlen = sizeof tvb;
    r = setsockopt(a, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    r2 = getsockopt(a, SOL_SOCKET, SO_RCVTIMEO, &tvb, &tvlen);
    // Linux keeps it in its clock's ticks (4 ms at 250 Hz): it reads back rounded up to one.
    CHECK("SO_RCVTIMEO reads back as it was set", r == 0 && r2 == 0 && tvb.tv_sec == 0 && tvb.tv_usec >= 250000 && tvb.tv_usec < 260000);
    // And a read with nothing to read waits that long.
    clock_gettime(CLOCK_MONOTONIC, &t0);
    r = (int)recv(a, got5, sizeof got5, 0);
    int e = errno;
    ms = ms_since(&t0);
    CHECK("a read past SO_RCVTIMEO fails with EAGAIN", r == -1 && (e == EAGAIN || e == EWOULDBLOCK) && ms >= 200 && ms < 2000);
    close(a);
    close(b);

    // A port nobody listens on: a listener's, closed again.
    l = listener(&where);
    close(l);
    step = "a refused connect";
    int c = socket(AF_INET, SOCK_STREAM, 0);
    r = connect(c, (struct sockaddr*)&where, sizeof where);
    e = errno;
    CHECK("a connect to a closed port is refused", r == -1 && e == ECONNREFUSED);
    close(c);
    // The same without blocking: refused at once, or in progress and then refused, which poll and SO_ERROR say.
    c = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    r = connect(c, (struct sockaddr*)&where, sizeof where);
    e = errno;
    int refused = 0;
    if (r == -1 && e == EINPROGRESS) {
        struct pollfd cp = {c, POLLOUT, 0};
        int pr = poll(&cp, 1, 5000);
        int soerr = 0;
        socklen_t sl = sizeof soerr;
        getsockopt(c, SOL_SOCKET, SO_ERROR, &soerr, &sl);
        refused = pr == 1 && (cp.revents & (POLLOUT | POLLERR | POLLHUP)) && soerr == ECONNREFUSED;
    } else {
        refused = r == -1 && e == ECONNREFUSED;
    }
    CHECK("a connect that does not block is refused, and poll says when", refused);
    close(c);

    // A ready descriptor added to an epoll while another thread waits on it: the wait sees it.
    step = "an epoll wait while its list changes";
    int ep = epoll_create1(EPOLL_CLOEXEC);
    int q[2];
    if (pipe(q) != 0) return 1;
    write(q[1], "y", 1);
    ep_wait_fd = ep;
    pthread_create(&t, NULL, epoll_waiter, NULL);
    // The thread waits by now, on an empty list.
    usleep(100000);
    struct epoll_event ev = {EPOLLIN, {.fd = q[0]}};
    epoll_ctl(ep, EPOLL_CTL_ADD, q[0], &ev);
    pthread_join(t, NULL);
    CHECK("epoll_wait sees a ready descriptor added while it waits", ep_waited == 1 && ep_waited_ms < 1500);
    close(q[0]);
    close(q[1]);
    close(ep);

    // A descriptor in a set, closed, and its number given to a new pipe: the new one is a new entry, with its own data.
    ep = epoll_create1(EPOLL_CLOEXEC);
    int x[2];
    if (pipe(x) != 0) return 1;
    struct epoll_event e1 = {EPOLLIN, {.u32 = 1}};
    epoll_ctl(ep, EPOLL_CTL_ADD, x[0], &e1);
    int number = x[0];
    close(x[0]);
    close(x[1]);
    int y[2];
    if (pipe(y) != 0) return 1;
    // The same number for the new read end, whatever else took numbers meanwhile.
    if (y[0] != number) {
        dup2(y[0], number);
        close(y[0]);
        y[0] = number;
    }
    struct epoll_event e2 = {EPOLLIN, {.u32 = 2}};
    r = epoll_ctl(ep, EPOLL_CTL_ADD, y[0], &e2);
    CHECK("epoll takes a number closed and opened again as a new entry", r == 0);
    write(y[1], "z", 1);
    struct epoll_event out[4];
    int n = epoll_wait(ep, out, 4, 1000);
    CHECK("the new entry is told of with its own data", n == 1 && out[0].data.u32 == 2);
    close(y[0]);
    close(y[1]);
    close(ep);

    // Edge-triggered: told once for each change, however long it stays ready. Level-triggered: told while it is.
    ep = epoll_create1(EPOLL_CLOEXEC);
    int z[2], lv[2];
    if (pipe(z) != 0 || pipe(lv) != 0) return 1;
    step = "edge-triggered epoll";
    struct epoll_event et = {EPOLLIN | EPOLLET, {.u32 = 7}};
    epoll_ctl(ep, EPOLL_CTL_ADD, z[0], &et);
    write(z[1], "a", 1);
    int n1 = epoll_wait(ep, out, 4, 1000);
    // Nothing new: no second word.
    int n2 = epoll_wait(ep, out, 4, 100);
    // More data: a new edge.
    write(z[1], "b", 1);
    int n3 = epoll_wait(ep, out, 4, 1000);
    CHECK("an edge-triggered entry is told once for each change", n1 == 1 && n2 == 0 && n3 == 1 && out[0].data.u32 == 7);
    epoll_ctl(ep, EPOLL_CTL_DEL, z[0], NULL);
    struct epoll_event lt = {EPOLLIN, {.u32 = 8}};
    epoll_ctl(ep, EPOLL_CTL_ADD, lv[0], &lt);
    write(lv[1], "c", 1);
    n1 = epoll_wait(ep, out, 4, 1000);
    n2 = epoll_wait(ep, out, 4, 1000);
    CHECK("a level-triggered entry is told while it stays ready", n1 == 1 && n2 == 1 && out[0].data.u32 == 8);
    close(z[0]);
    close(z[1]);
    close(lv[0]);
    close(lv[1]);
    close(ep);

    // An epoll inside another, edge-triggered there: each new event inside is a new edge outside, also after the inner
    // one's descriptor was read empty.
    step = "an epoll inside an epoll";
    int outer = epoll_create1(EPOLL_CLOEXEC), inner = epoll_create1(EPOLL_CLOEXEC);
    int np[2];
    if (pipe(np) != 0) return 1;
    struct epoll_event in_ev = {EPOLLIN, {.u32 = 1}}, out_ev = {EPOLLIN | EPOLLET, {.u32 = 2}};
    epoll_ctl(inner, EPOLL_CTL_ADD, np[0], &in_ev);
    epoll_ctl(outer, EPOLL_CTL_ADD, inner, &out_ev);
    write(np[1], "a", 1);
    int m1 = epoll_wait(outer, out, 4, 1000);
    char c1;
    read(np[0], &c1, 1);
    write(np[1], "b", 1);
    int m2 = epoll_wait(outer, out, 4, 1000);
    CHECK("an edge-triggered epoll inside another is told of each new event in it", m1 == 1 && m2 == 1 && out[0].data.u32 == 2);
    // Put inside the one it is in: a loop, refused.
    r = epoll_ctl(inner, EPOLL_CTL_ADD, outer, &in_ev);
    e = errno;
    CHECK("an epoll put inside one that is inside it fails with ELOOP", r == -1 && e == ELOOP);
    close(np[0]);
    close(np[1]);
    close(inner);
    close(outer);

    // A pipe's write end closed while another thread's epoll waits on it: the reader sees the pipe's end at once.
    step = "a close while an epoll waits";
    int cp[2];
    if (pipe(cp) != 0) return 1;
    int ex = eventfd(0, EFD_CLOEXEC);
    sleeper_ep = epoll_create1(EPOLL_CLOEXEC);
    struct epoll_event wev = {EPOLLOUT | EPOLLET, {.u32 = 1}}, xev = {EPOLLIN, {.u32 = 2}};
    epoll_ctl(sleeper_ep, EPOLL_CTL_ADD, cp[1], &wev);
    epoll_ctl(sleeper_ep, EPOLL_CTL_ADD, ex, &xev);
    // The write end's edge, told once: the waits after it sleep.
    epoll_wait(sleeper_ep, out, 4, 0);
    reader_fd = cp[0];
    pthread_t sleeper, reader;
    pthread_create(&sleeper, NULL, epoll_sleeper, NULL);
    pthread_create(&reader, NULL, one_byte_reader, (void*)0);
    // Both wait by now.
    usleep(200000);
    clock_gettime(CLOCK_MONOTONIC, &t0);
    close(cp[1]);
    pthread_join(reader, NULL);
    ms = ms_since(&t0);
    CHECK("a pipe's reader sees its end when the writer is closed while an epoll waits on it", reader_got[0] == 0 && ms < 1000);
    pthread_join(sleeper, NULL);
    close(cp[0]);
    close(ex);
    close(sleeper_ep);

    // Two threads reading one pipe: a byte each, and no false end for the one the first byte did not go to.
    step = "two readers of one pipe";
    int wrong = 0;
    for (int round = 0; round < 20; ++round) {
        int tp[2];
        if (pipe(tp) != 0) return 1;
        reader_fd = tp[0];
        reader_got[0] = reader_got[1] = -2;
        pthread_t r1, r2;
        pthread_create(&r1, NULL, one_byte_reader, (void*)0);
        pthread_create(&r2, NULL, one_byte_reader, (void*)1);
        usleep(20000);
        write(tp[1], "1", 1);
        usleep(20000);
        write(tp[1], "2", 1);
        pthread_join(r1, NULL);
        pthread_join(r2, NULL);
        if (reader_got[0] != 1 || reader_got[1] != 1) ++wrong;
        close(tp[0]);
        close(tp[1]);
    }
    CHECK("two threads reading one pipe each get a byte, and no false end", wrong == 0);

    // readv on a pipe holding ten bytes, into four and then sixty-four: the ten, spread over both.
    step = "readv on a pipe";
    int v[2];
    if (pipe(v) != 0) return 1;
    write(v[1], "0123456789", 10);
    char b1[4], b2[64];
    struct iovec iov[2] = {{b1, sizeof b1}, {b2, sizeof b2}};
    ssize_t got = readv(v[0], iov, 2);
    CHECK("readv spreads what it reads over its buffers", got == 10 && memcmp(b1, "0123", 4) == 0 && memcmp(b2, "456789", 6) == 0);
    // Four bytes, which fill the first buffer to its end: the four at once, and no wait for more.
    write(v[1], "abcd", 4);
    late_fd = v[1];
    pthread_create(&t, NULL, write_late, NULL);
    clock_gettime(CLOCK_MONOTONIC, &t0);
    got = readv(v[0], iov, 2);
    ms = ms_since(&t0);
    CHECK("readv gives what a pipe holds without waiting for more", got == 4 && ms < 1000 && memcmp(b1, "abcd", 4) == 0);
    pthread_join(t, NULL);
    // The late four bytes: FIONREAD counts them from either end of the pipe.
    int on_read = -1, on_write = -1;
    ioctl(v[0], FIONREAD, &on_read);
    ioctl(v[1], FIONREAD, &on_write);
    CHECK("FIONREAD on either end of a pipe counts its bytes", on_read == 4 && on_write == 4);
    char drain[8];
    CHECK("the late bytes read", read(v[0], drain, sizeof drain) == 4);
    // Nothing asked for, from the pipe now empty: 0 at once, by readv and by read.
    step = "a read of nothing";
    struct iovec none[2] = {{b1, 0}, {b2, 0}};
    clock_gettime(CLOCK_MONOTONIC, &t0);
    ssize_t g0 = readv(v[0], none, 2), g1 = readv(v[0], none, 1), g2 = read(v[0], drain, 0);
    ms = ms_since(&t0);
    CHECK("a read of nothing returns 0 at once from an empty pipe", g0 == 0 && g1 == 0 && g2 == 0 && ms < 1000);
    close(v[0]);
    close(v[1]);

    // Two threads appending to one file through descriptors of their own: every record lands whole, none over another.
    step = "appends from two descriptors";
    int fd = open(kAppendPath, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd >= 0) close(fd);
    pthread_t a1, a2;
    pthread_create(&a1, NULL, appender, (void*)(intptr_t)'A');
    pthread_create(&a2, NULL, appender, (void*)(intptr_t)'B');
    pthread_join(a1, NULL);
    pthread_join(a2, NULL);
    struct stat st;
    int whole = stat(kAppendPath, &st) == 0 && st.st_size == 2 * kRecords * kRecord;
    int counts[2] = {0, 0};
    fd = open(kAppendPath, O_RDONLY | O_CLOEXEC);
    char rec[kRecord];
    while (fd >= 0 && read(fd, rec, sizeof rec) == (ssize_t)sizeof rec) {
        int same = 1;
        for (int i = 1; i < kRecord; ++i) same &= rec[i] == rec[0];
        if (same && (rec[0] == 'A' || rec[0] == 'B')) counts[rec[0] - 'A']++;
    }
    if (fd >= 0) close(fd);
    CHECK("appends from two descriptors at once lose nothing", whole && counts[0] == kRecords && counts[1] == kRecords);
    if (!whole || counts[0] != kRecords || counts[1] != kRecords) printf("     %lld bytes, %d A and %d B\n", (long long)st.st_size, counts[0], counts[1]);
    // An appending descriptor's offset is after what it wrote.
    fd = open(kAppendPath, O_WRONLY | O_APPEND | O_CLOEXEC);
    write(fd, "12345678", 8);
    off_t at = lseek(fd, 0, SEEK_CUR);
    close(fd);
    CHECK("an append leaves the offset at the end", at == 2 * kRecords * kRecord + 8);
    unlink(kAppendPath);

    // A directory of three files, listed, listed again from its start, and again from a place in it.
    step = "a directory listed again";
    mkdir("descriptors.dir", 0700);
    for (int i = 0; i < 3; ++i) {
        char name[64];
        snprintf(name, sizeof name, "descriptors.dir/f%d", i);
        int f = open(name, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        if (f >= 0) close(f);
    }
    DIR* d = opendir("descriptors.dir");
    char first[256], again[256], after[256];
    list_rest(d, first, sizeof first);
    rewinddir(d);
    list_rest(d, again, sizeof again);
    CHECK("a directory listed again from its start gives the same names", d && strlen(first) > 0 && strcmp(first, again) == 0);
    if (d) closedir(d);
    // A place in it, through the system calls with its 64 bits (a Linux file system's places are hashes, which
    // telldir's long cuts on a 32-bit system): the names after the first, listed again from the first's place.
    int dfd = open("descriptors.dir", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    char all[256];
    int64_t place = -1;
    list_records(dfd, all, sizeof all, &place);
    off64_t moved = lseek64(dfd, place, SEEK_SET);
    list_records(dfd, after, sizeof after, NULL);
    const char* rest = strchr(all, '/');
    CHECK("a directory listed again from a place in it", dfd >= 0 && moved == place && rest && strcmp(rest + 1, after) == 0 && strlen(after) > 0);
    if (dfd >= 0) close(dfd);
    for (int i = 0; i < 3; ++i) {
        char name[64];
        snprintf(name, sizeof name, "descriptors.dir/f%d", i);
        unlink(name);
    }
    rmdir("descriptors.dir");

    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 0;
}
