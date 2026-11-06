// A store into a PROT_NONE page must fault, as a stack overflow into a thread's guard page does.
// Run with --fastmem: translated code then reaches memory without the guest page table, so only
// the host's own page protection can stop it. The runtime ends the process on the fault; reaching
// the line after the store is the failure.
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    // Six 16 KB host pages' worth, the middle four made PROT_NONE: at least one whole host page
    // is inaccessible even where host pages are 16 KB.
    char* p = mmap(NULL, 96 << 10, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED || mprotect(p + (16 << 10), 64 << 10, PROT_NONE) != 0) {
        printf("FAIL: cannot set up the PROT_NONE pages\n");
        return 1;
    }
    volatile char* target = (volatile char*)((((uintptr_t)p + (16 << 10)) + (16 << 10) - 1) & ~(uintptr_t)((16 << 10) - 1)) + 8;
    printf("touching a PROT_NONE page at %p\n", (void*)target);
    *target = 1;
    printf("FAIL: the PROT_NONE page did not fault\n");
    return 0;
}
