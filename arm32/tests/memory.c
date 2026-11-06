// Memory system calls at their edges: mprotect of no bytes, mremap growing the start of a larger
// mapping, madvise(MADV_DONTNEED) on anonymous and on file memory, mincore over a hole, and where
// mmap puts a mapping whose hint is below the lowest guest address the runtime hands out.
// Prints one line per check.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static int failures = 0;
#define CHECK(name, cond) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "ok  " : "FAIL", name); if (!ok_) failures++; } while (0)

enum { kPage = 4096 };

// True when every page of [p, p + len) lies inside some line of /proc/self/maps (up to 64 pages).
static int listed(uintptr_t p, size_t len) {
    FILE* f = fopen("/proc/self/maps", "r");
    if (!f) return 0;
    size_t pages = len / kPage;
    char seen[64] = {0};
    char line[512];
    while (fgets(line, sizeof line, f)) {
        unsigned long lo, hi;
        if (sscanf(line, "%lx-%lx", &lo, &hi) != 2) continue;
        for (size_t i = 0; i < pages && i < 64; i++) {
            uintptr_t a = p + i * kPage;
            if (a >= lo && a < hi) seen[i] = 1;
        }
    }
    fclose(f);
    for (size_t i = 0; i < pages && i < 64; i++) {
        if (!seen[i]) return 0;
    }
    return 1;
}

// The process's resident memory in bytes, as /proc/self/statm counts it.
static long resident(void) {
    FILE* f = fopen("/proc/self/statm", "r");
    long size = 0, rss = 0;
    if (f) {
        if (fscanf(f, "%ld %ld", &size, &rss) != 2) rss = 0;
        fclose(f);
    }
    return rss * sysconf(_SC_PAGESIZE);
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);

    // mprotect of zero bytes changes nothing (Linux returns 0); the mapping stays whole, so no
    // later mmap can be placed over part of it.
    char* m = mmap(NULL, 4 * kPage, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    int r = mprotect(m + kPage, 0, PROT_READ);
    CHECK("mprotect of no bytes inside a mapping keeps it whole", m != MAP_FAILED && r == 0 && listed((uintptr_t)m, 4 * kPage));

    // Growing the first page of a four-page mapping cannot happen in place (the next page is the
    // mapping's own): with MREMAP_MAYMOVE the page moves, and the other three stay where they are.
    char* a = mmap(NULL, 4 * kPage, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    memset(a, 0x33, 4 * kPage);
    a[0] = 0x44;
    char* b = mremap(a, kPage, 2 * kPage, MREMAP_MAYMOVE);
    CHECK("mremap growing the start of a mapping moves just that part",
          a != MAP_FAILED && b != MAP_FAILED && b != a && b[0] == 0x44 && listed((uintptr_t)a + kPage, 3 * kPage) && a[kPage] == 0x33);

    // MADV_DONTNEED: private anonymous memory reads as zero afterwards and goes back to the system.
    const size_t big = 16 << 20;
    char* z = mmap(NULL, big, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    memset(z, 7, big);
    long before = resident();
    r = madvise(z, big, MADV_DONTNEED);
    long after = resident();
    CHECK("madvise(MADV_DONTNEED) zeroes anonymous memory", z != MAP_FAILED && r == 0 && z[0] == 0 && z[big - 1] == 0);
    printf("     resident before %ld KB, after %ld KB\n", before >> 10, after >> 10);
    CHECK("madvise(MADV_DONTNEED) gives anonymous memory back", before - after >= (long)(big / 2));

    // A private file mapping keeps the file's contents (it reads them again; it never reads zeros).
    int fd = open("madvise.tmp", O_RDWR | O_CREAT | O_TRUNC, 0600);
    char fill[2 * kPage];
    memset(fill, 'F', sizeof fill);
    int wrote = fd >= 0 && write(fd, fill, sizeof fill) == (ssize_t)sizeof fill;
    char* fm = wrote ? mmap(NULL, sizeof fill, PROT_READ, MAP_PRIVATE, fd, 0) : MAP_FAILED;
    r = fm != MAP_FAILED ? madvise(fm, sizeof fill, MADV_DONTNEED) : -1;
    CHECK("madvise(MADV_DONTNEED) keeps a file mapping's contents", fm != MAP_FAILED && r == 0 && fm[0] == 'F' && fm[sizeof fill - 1] == 'F');
    if (fd >= 0) close(fd);
    unlink("madvise.tmp");

    // mincore over a hole fails with ENOMEM, as for any range that is not all mapped.
    unsigned char vec[4];
    char* h = mmap(NULL, 4 * kPage, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    munmap(h + kPage, kPage);
    int whole = mincore(h, kPage, vec);
    errno = 0;
    int hole = mincore(h, 4 * kPage, vec);
    CHECK("mincore over a hole fails with ENOMEM", h != MAP_FAILED && whole == 0 && hole == -1 && errno == ENOMEM);

    // Guest pointers below 128 MB would read as buffer offsets to the graphics bridge: a hint
    // there is not taken.
    void* low = mmap((void*)0x01000000, kPage, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    printf("     mapping hinted at 0x01000000 placed at %p\n", low);
    CHECK("a hint below 0x08000000 is not taken", low != MAP_FAILED && (uintptr_t)low >= 0x08000000);

    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 0;
}
