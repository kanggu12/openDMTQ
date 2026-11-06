// System calls whose 32-bit forms the runtime converts: select (the C library makes it pselect6),
// sched_getaffinity with the C library's 4-byte CPU set, fcntl locks and owners with 32-bit
// structures, the old stat call's 64-byte structure, and output pointers that are NULL, which
// must fail with EFAULT instead of bringing the process down. Prints one line per check.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/syscall.h>
#include <sys/system_properties.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

static long ms_since(const struct timespec* t0) {
    struct timespec t1;
    clock_gettime(CLOCK_MONOTONIC, &t1);
    return (t1.tv_sec - t0->tv_sec) * 1000 + (t1.tv_nsec - t0->tv_nsec) / 1000000;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);

    // select with nothing to watch is a sleep: it times out and counts the timeout down.
    struct timeval tv = {0, 30000};
    struct timespec t0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int r = select(0, NULL, NULL, NULL, &tv);
    long ms = ms_since(&t0);
    CHECK("select times out", r == 0 && ms >= 20 && tv.tv_sec == 0 && tv.tv_usec < 30000);

    // select on a pipe with a byte in it.
    int p[2];
    pipe(p);
    write(p[1], "x", 1);
    fd_set rd;
    FD_ZERO(&rd);
    FD_SET(p[0], &rd);
    struct timeval tv2 = {1, 0};
    r = select(p[0] + 1, &rd, NULL, NULL, &tv2);
    CHECK("select sees a readable pipe", r == 1 && FD_ISSET(p[0], &rd));

    // The 32-bit C library's CPU set is 4 bytes; the 64-bit kernel wants multiples of 8.
    cpu_set_t set;
    CPU_ZERO(&set);
    r = sched_getaffinity(0, sizeof set, &set);
    CHECK("sched_getaffinity with the 4-byte cpu_set_t", r == 0 && CPU_COUNT(&set) > 0);

    // A record lock through the 32-bit struct flock, and the lock query that finds no conflict
    // (a process does not conflict with its own locks).
    int fd = open("calls.tmp", O_RDWR | O_CREAT | O_TRUNC, 0600);
    write(fd, "0123456789abcdef", 16);
    struct flock fl;
    memset(&fl, 0, sizeof fl);
    fl.l_type = F_WRLCK;
    fl.l_whence = SEEK_SET;
    fl.l_len = 8;
    r = fcntl(fd, F_SETLK, &fl);
    struct flock q;
    memset(&q, 0, sizeof q);
    q.l_type = F_WRLCK;
    q.l_whence = SEEK_SET;
    q.l_len = 8;
    int r2 = fcntl(fd, F_GETLK, &q);
    CHECK("fcntl F_SETLK and F_GETLK with the 32-bit struct flock", r == 0 && r2 == 0 && q.l_type == F_UNLCK);

    // F_GETOWN_EX writes a structure through a pointer, which must be a guest address.
    struct f_owner_ex owner = {-1, -1};
    r = fcntl(fd, F_GETOWN_EX, &owner);
    CHECK("fcntl F_GETOWN_EX writes its structure", r == 0 && owner.pid == 0);

    // The old stat call (106) fills the 64-byte struct stat, not the 104-byte struct stat64.
    struct {
        unsigned char data[64];
        unsigned char canary[48];
    } st;
    memset(&st, 0xab, sizeof st);
    r = syscall(106, "calls.tmp", &st);
    uint32_t size = 0;
    memcpy(&size, st.data + 20, sizeof size);
    CHECK("old stat fills a 64-byte structure", r == 0 && size == 16 && st.canary[0] == 0xab && st.canary[39] == 0xab);
    close(fd);
    unlink("calls.tmp");

    // The guest's own property area: an Android 6 C library cannot read a newer system's.
    char abi[PROP_VALUE_MAX] = "";
    __system_property_get("ro.product.cpu.abi", abi);
    char sdk[PROP_VALUE_MAX] = "";
    __system_property_get("ro.build.version.sdk", sdk);
    printf("     ro.product.cpu.abi=%s ro.build.version.sdk=%s\n", abi, sdk);
    CHECK("system properties for a 32-bit ARM process", strcmp(abi, "armeabi-v7a") == 0 && sdk[0] != 0);

    // NULL output pointers: EFAULT from the call, as the kernel answers. These ran the host into a
    // null pointer before, so they come last.
    errno = 0;
    long c = syscall(__NR_getcwd, NULL, 128);
    CHECK("getcwd into NULL fails with EFAULT", c == -1 && errno == EFAULT);
    errno = 0;
    c = syscall(__NR_clock_gettime, CLOCK_MONOTONIC, NULL);
    CHECK("clock_gettime into NULL fails with EFAULT", c == -1 && errno == EFAULT);

    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 0;
}
