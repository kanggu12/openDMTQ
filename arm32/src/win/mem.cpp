// The host process's memory on Windows, with Linux's calls: anonymous mappings reserved (PROT_NONE) or committed,
// protection changes that commit what they open, MADV_DONTNEED that gives zero pages back, and read-only file mappings
// (a view from the file's 64 KB-aligned offset, the pointer moved to the offset asked for). The guest's 4 GB block is
// one reservation (Memory::init), in which pages are committed and protected 4 KB at a time.
#include "layer.h"

#include <map>

using namespace arm32::win;

namespace {

DWORD protection(int prot) {
    const bool r = prot & PROT_READ, w = prot & PROT_WRITE, x = prot & PROT_EXEC;
    if (x) return w ? PAGE_EXECUTE_READWRITE : r ? PAGE_EXECUTE_READ : PAGE_EXECUTE;
    if (w) return PAGE_READWRITE;
    if (r) return PAGE_READONLY;
    return PAGE_NOACCESS;
}

// File views: the address handed out, and the view's own base, which UnmapViewOfFile wants.
std::mutex g_views_lock;
std::map<void*, void*>& views() {
    static auto* m = new std::map<void*, void*>;
    return *m;
}

}  // namespace

namespace arm32::posix {

void* mmap(void* addr, std::size_t length, int prot, int flags, int fd, long long offset) {
    if (!length) {
        errno = EINVAL;
        return MAP_FAILED;
    }
    if (!(flags & MAP_ANONYMOUS)) {
        // A file's contents, read only: a view of a mapping of it.
        std::shared_ptr<Fd> f = fd_get(fd);
        if (!f) {
            errno = EBADF;
            return MAP_FAILED;
        }
        if (prot & PROT_WRITE) {
            // Writable file mappings: their contents copied into private memory.
            void* p = VirtualAlloc(nullptr, length, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            if (!p) {
                errno = ENOMEM;
                return MAP_FAILED;
            }
            f->pread(p, length, offset);
            return p;
        }
        int ffd = fd;
        HANDLE file = INVALID_HANDLE_VALUE;
        // Only a file on disk can be mapped; anything else (a memfd) is copied.
        if (auto copy = dynamic_cast<Fd*>(f.get()); copy && f->path.rfind("/memfd:", 0) != 0) {
            file = CreateFileW(wide(f->path).c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
        }
        (void)ffd;
        if (file == INVALID_HANDLE_VALUE) {
            void* p = VirtualAlloc(nullptr, length, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            if (!p) {
                errno = ENOMEM;
                return MAP_FAILED;
            }
            f->pread(p, length, offset);
            DWORD old;
            VirtualProtect(p, length, protection(prot), &old);
            return p;
        }
        HANDLE map = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0, nullptr);
        CloseHandle(file);
        if (!map) {
            errno = errno_of(GetLastError());
            return MAP_FAILED;
        }
        SYSTEM_INFO si;
        GetSystemInfo(&si);
        long long aligned = offset - offset % si.dwAllocationGranularity;
        std::size_t extra = static_cast<std::size_t>(offset - aligned);
        void* view = MapViewOfFile(map, FILE_MAP_READ, static_cast<DWORD>(aligned >> 32), static_cast<DWORD>(aligned), length + extra);
        CloseHandle(map);
        if (!view) {
            errno = errno_of(GetLastError());
            return MAP_FAILED;
        }
        void* p = static_cast<std::uint8_t*>(view) + extra;
        std::lock_guard<std::mutex> l(g_views_lock);
        views()[p] = view;
        return p;
    }
    // Anonymous: reserved only when it gives no access (the guest's block), committed otherwise. A fixed address must
    // lie in a reservation of the caller's.
    if (flags & MAP_FIXED) {
        if (prot == PROT_NONE) {
            VirtualFree(addr, length, MEM_DECOMMIT);
            return addr;
        }
        if (!VirtualAlloc(addr, length, MEM_COMMIT, protection(prot))) {
            errno = ENOMEM;
            return MAP_FAILED;
        }
        return addr;
    }
    void* p = VirtualAlloc(addr, length, prot == PROT_NONE ? MEM_RESERVE : (MEM_RESERVE | MEM_COMMIT), protection(prot));
    if (!p && addr) p = VirtualAlloc(nullptr, length, prot == PROT_NONE ? MEM_RESERVE : (MEM_RESERVE | MEM_COMMIT), protection(prot));
    if (!p) {
        errno = ENOMEM;
        return MAP_FAILED;
    }
    return p;
}

int munmap(void* addr, std::size_t length) {
    {
        std::lock_guard<std::mutex> l(g_views_lock);
        auto it = views().find(addr);
        if (it != views().end()) {
            UnmapViewOfFile(it->second);
            views().erase(it);
            return 0;
        }
    }
    // A whole allocation of the layer's goes; part of one (the guest's block) is decommitted.
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(addr, &mbi, sizeof mbi) && mbi.AllocationBase == addr && mbi.RegionSize >= length) {
        VirtualFree(addr, 0, MEM_RELEASE);
        return 0;
    }
    VirtualFree(addr, length, MEM_DECOMMIT);
    return 0;
}

int mprotect(void* addr, std::size_t length, int prot) {
    if (!length) return 0;
    if (prot != PROT_NONE) {
        // Opening pages of a reservation commits them; committed pages keep their contents.
        if (!VirtualAlloc(addr, length, MEM_COMMIT, protection(prot))) return fail(ENOMEM);
    }
    DWORD old;
    if (!VirtualProtect(addr, length, protection(prot), &old)) return fail_win32();
    return 0;
}

int madvise(void* addr, std::size_t length, int advice) {
    if (advice != MADV_DONTNEED) return 0;
    // Zero pages from now on, as Linux gives an anonymous mapping after MADV_DONTNEED, with the protection they had.
    MEMORY_BASIC_INFORMATION mbi;
    auto* p = static_cast<std::uint8_t*>(addr);
    std::uint8_t* end = p + length;
    while (p < end) {
        if (!VirtualQuery(p, &mbi, sizeof mbi)) break;
        std::size_t run = std::min<std::size_t>(static_cast<std::size_t>(static_cast<std::uint8_t*>(mbi.BaseAddress) + mbi.RegionSize - p),
                                                static_cast<std::size_t>(end - p));
        if (mbi.State == MEM_COMMIT) {
            DWORD prot = mbi.Protect;
            VirtualFree(p, run, MEM_DECOMMIT);
            VirtualAlloc(p, run, MEM_COMMIT, prot == 0 ? PAGE_NOACCESS : prot);
        }
        p += run;
    }
    return 0;
}

void* mremap(void*, std::size_t, std::size_t, int, ...) {
    errno = ENOSYS;
    return MAP_FAILED;
}

}  // namespace arm32::posix
