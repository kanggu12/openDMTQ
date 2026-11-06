// Program loading, the way the Linux kernel's ELF loader starts a dynamically linked program:
// map the executable, map its interpreter (the 32-bit Android linker), build the initial stack
// with arguments, environment and auxiliary vector, and start at the interpreter's entry point.
// From there the guest's own linker loads the libraries and runs the program.
#include "runtime.h"

#include <cerrno>
#include <cstring>
#include <elf.h>
#include <fcntl.h>
#include <random>
#include <sys/stat.h>
#include <unistd.h>

namespace arm32 {

namespace {

// Where a position-independent executable is placed.
constexpr gaddr kExeBase = 0x08000000;
// Main thread stack, at the top of the 3 GB user range like 32-bit ARM Linux.
constexpr gaddr kStackTop = 0xbf000000;
constexpr std::uint32_t kStackSize = 8 * 1024 * 1024;
// The kernel's "user helpers" page that old ARM code calls for atomics and the thread pointer.
constexpr gaddr kKuserPage = 0xffff0000;

// ARM HWCAP bits the guest sees in AT_HWCAP: an ARMv7 core with VFPv4, NEON and integer divide.
constexpr std::uint32_t kHwcap = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 7) |  // swp half thumb 26bit fastmult vfp
                                 (1 << 12) | (1 << 13) | (1 << 15) | (1 << 16) | (1 << 17) | (1 << 18) | (1 << 19) |  // neon vfpv3 tls vfpv4 idiva idivt vfpd32
                                 (1 << 20);  // lpae

struct Image {
    gaddr bias = 0;        // load address minus link address
    gaddr phdr = 0;        // where the program headers are in guest memory
    std::uint32_t phnum = 0;
    gaddr entry = 0;
    gaddr end = 0;         // first page after the image
    std::string interp;    // PT_INTERP, empty if none
};

bool read_file(const std::string& path, std::vector<std::uint8_t>& out, std::string& error) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        error = path + ": " + strerror(errno);
        return false;
    }
    struct stat st {};
    fstat(fd, &st);
    out.resize(static_cast<std::size_t>(st.st_size));
    std::size_t done = 0;
    while (done < out.size()) {
        ssize_t n = read(fd, out.data() + done, out.size() - done);
        if (n <= 0) break;
        done += static_cast<std::size_t>(n);
    }
    close(fd);
    if (done != out.size()) {
        error = path + ": short read";
        return false;
    }
    return true;
}

// Maps one ELF file. Position-independent files go at `want` when it is non-zero, else wherever
// mmap would put them; fixed-address files go at their link address.
bool map_elf(Process& proc, const std::string& host_file, const std::string& guest_name, gaddr want, Image& img,
             std::string& error) {
    std::vector<std::uint8_t> file;
    if (!read_file(host_file, file, error)) return false;
    if (file.size() < sizeof(Elf32_Ehdr)) {
        error = guest_name + ": not an ELF file";
        return false;
    }
    auto* eh = reinterpret_cast<const Elf32_Ehdr*>(file.data());
    if (std::memcmp(eh->e_ident, ELFMAG, SELFMAG) != 0 || eh->e_ident[EI_CLASS] != ELFCLASS32 || eh->e_machine != EM_ARM) {
        error = guest_name + ": not a 32-bit ARM ELF file";
        return false;
    }
    if (eh->e_phoff + std::size_t{eh->e_phnum} * sizeof(Elf32_Phdr) > file.size()) {
        error = guest_name + ": bad program headers";
        return false;
    }
    auto* ph = reinterpret_cast<const Elf32_Phdr*>(file.data() + eh->e_phoff);
    // The span every PT_LOAD segment covers, in link addresses.
    std::uint64_t lo = UINT64_MAX, hi = 0;
    for (int i = 0; i < eh->e_phnum; ++i) {
        if (ph[i].p_type != PT_LOAD) continue;
        lo = std::min<std::uint64_t>(lo, page_down(ph[i].p_vaddr));
        hi = std::max<std::uint64_t>(hi, page_up(std::uint64_t{ph[i].p_vaddr} + ph[i].p_memsz));
    }
    if (lo >= hi) {
        error = guest_name + ": no loadable segments";
        return false;
    }
    // Reserve the whole span at once so the segments keep their relative positions.
    bool pie = eh->e_type == ET_DYN;
    std::int64_t at = pie ? proc.mem.map(want, static_cast<std::uint32_t>(hi - lo), kProtRead | kProtWrite | kProtExec,
                                         want != 0, guest_name)
                          : proc.mem.map(static_cast<gaddr>(lo), static_cast<std::uint32_t>(hi - lo),
                                         kProtRead | kProtWrite | kProtExec, true, guest_name);
    if (at < 0) {
        error = guest_name + ": cannot map: " + strerror(static_cast<int>(-at));
        return false;
    }
    img.bias = static_cast<gaddr>(at - static_cast<std::int64_t>(lo));
    img.end = static_cast<gaddr>(img.bias + hi);
    // Copy each segment's file bytes; the rest of the segment (.bss) is already zero.
    for (int i = 0; i < eh->e_phnum; ++i) {
        if (ph[i].p_type != PT_LOAD || ph[i].p_filesz == 0) continue;
        if (std::uint64_t{ph[i].p_offset} + ph[i].p_filesz > file.size()) {
            error = guest_name + ": segment beyond end of file";
            return false;
        }
        std::memcpy(proc.mem.host(img.bias + ph[i].p_vaddr), file.data() + ph[i].p_offset, ph[i].p_filesz);
    }
    // Final protections per segment, so /proc/self/maps looks like a normal process.
    for (int i = 0; i < eh->e_phnum; ++i) {
        if (ph[i].p_type != PT_LOAD) continue;
        int prot = ((ph[i].p_flags & PF_R) ? kProtRead : 0) | ((ph[i].p_flags & PF_W) ? kProtWrite : 0) |
                   ((ph[i].p_flags & PF_X) ? kProtExec : 0);
        gaddr s = static_cast<gaddr>(page_down(img.bias + ph[i].p_vaddr));
        gaddr e = static_cast<gaddr>(page_up(std::uint64_t{img.bias} + ph[i].p_vaddr + ph[i].p_memsz));
        proc.mem.protect(s, e - s, prot);
    }
    // Program header address: PT_PHDR when present, else found through the segment holding it.
    img.phnum = eh->e_phnum;
    for (int i = 0; i < eh->e_phnum; ++i) {
        if (ph[i].p_type == PT_PHDR) img.phdr = img.bias + ph[i].p_vaddr;
    }
    if (!img.phdr) {
        for (int i = 0; i < eh->e_phnum; ++i) {
            if (ph[i].p_type == PT_LOAD && eh->e_phoff >= ph[i].p_offset && eh->e_phoff < ph[i].p_offset + ph[i].p_filesz) {
                img.phdr = img.bias + ph[i].p_vaddr + (eh->e_phoff - ph[i].p_offset);
            }
        }
    }
    img.entry = img.bias + eh->e_entry;
    for (int i = 0; i < eh->e_phnum; ++i) {
        if (ph[i].p_type == PT_INTERP && ph[i].p_offset + ph[i].p_filesz <= file.size()) {
            img.interp.assign(reinterpret_cast<const char*>(file.data() + ph[i].p_offset), ph[i].p_filesz);
            img.interp = img.interp.c_str();  // drop the trailing NUL
        }
    }
    return true;
}

// The "kuser helpers" page: __kuser_memory_barrier, __kuser_cmpxchg and __kuser_get_tls,
// written as ARM code with the kernel's own instruction sequences.
void map_kuser_page(Process& proc) {
    if (proc.mem.map(kKuserPage, kPageSize, kProtRead | kProtExec, true, "[vectors]") < 0) return;
    auto put = [&](gaddr at, std::initializer_list<std::uint32_t> words) {
        for (std::uint32_t w : words) {
            *proc.mem.ptr<std::uint32_t>(at) = w;
            at += 4;
        }
    };
    put(0xffff0f00, {0xe3a070ad, 0xef000000});  // mov r7, #173; svc 0: rt_sigreturn for handlers without a restorer
    put(0xffff0f20, {0xe30f7000, 0xe34070f0, 0xef000000});  // movw r7, #0xf000; movt r7, #0xf0; svc 0: kTrapReturn
    put(0xffff0fa0, {0xf57ff05b, 0xe12fff1e});  // dmb ish; bx lr
    put(0xffff0fc0, {0xe1923f9f, 0xe0533000, 0x01823f91, 0x03330001, 0x0afffffa, 0xe2730000, 0xe12fff1e});  // ldrex/strex loop
    put(0xffff0fe0, {0xee1d0f70, 0xe12fff1e});  // mrc p15, 0, r0, c13, c0, 3; bx lr
    *proc.mem.ptr<std::uint32_t>(0xffff0ffc) = 3;  // __kuser_helper_version
}

}  // namespace

bool load_program(Process& proc, EntryState& entry, std::string& error) {
    // The executable, at its fixed address or at kExeBase when position independent.
    Image exe;
    if (!map_elf(proc, proc.host_path(proc.exe_path), proc.exe_path, kExeBase, exe, error)) return false;
    // Its interpreter, wherever mmap puts it, like the kernel does.
    Image interp;
    bool has_interp = !exe.interp.empty();
    if (has_interp && !map_elf(proc, proc.host_path(exe.interp), exe.interp, 0, interp, error)) return false;
    map_kuser_page(proc);
    // The program break starts after the executable's highest page.
    proc.mem.brk_start = proc.mem.brk_end = exe.end;

    // Stack: strings at the top, then AT_RANDOM bytes, then the pointer arrays the linker reads.
    std::int64_t st = proc.mem.map(kStackTop - kStackSize, kStackSize, kProtRead | kProtWrite, true, "[stack]");
    if (st < 0) {
        error = "cannot map the stack";
        return false;
    }
    gaddr sp = kStackTop;
    auto push_bytes = [&](const void* data, std::size_t n) {
        sp -= static_cast<gaddr>(n);
        std::memcpy(proc.mem.host(sp), data, n);
        return sp;
    };
    auto push_str = [&](const std::string& s) { return push_bytes(s.c_str(), s.size() + 1); };
    gaddr execfn = push_str(proc.exe_path);
    std::vector<gaddr> argv_ptrs, env_ptrs;
    for (auto& a : proc.argv) argv_ptrs.push_back(push_str(a));
    for (auto& e : proc.envp) env_ptrs.push_back(push_str(e));
    gaddr platform = push_str("v7l");
    std::uint8_t random_bytes[16];
    std::random_device rd;
    for (auto& b : random_bytes) b = static_cast<std::uint8_t>(rd());
    gaddr at_random = push_bytes(random_bytes, sizeof random_bytes);

    std::vector<std::uint32_t> aux = {
        AT_PHDR, exe.phdr, AT_PHENT, sizeof(Elf32_Phdr), AT_PHNUM, exe.phnum, AT_PAGESZ, kPageSize,
        AT_BASE, has_interp ? interp.bias : 0, AT_FLAGS, 0, AT_ENTRY, exe.entry,
        AT_UID, static_cast<std::uint32_t>(getuid()), AT_EUID, static_cast<std::uint32_t>(geteuid()),
        AT_GID, static_cast<std::uint32_t>(getgid()), AT_EGID, static_cast<std::uint32_t>(getegid()),
        AT_SECURE, 0, AT_RANDOM, at_random, AT_HWCAP, kHwcap, AT_HWCAP2, 0, AT_CLKTCK, 100,
        AT_PLATFORM, platform, AT_EXECFN, execfn, AT_NULL, 0,
    };
    // argc, argv[], NULL, envp[], NULL, auxv[]; sp ends 8-byte aligned at argc.
    std::size_t words = 1 + argv_ptrs.size() + 1 + env_ptrs.size() + 1 + aux.size();
    sp = static_cast<gaddr>((sp - words * 4) & ~gaddr{7});
    gaddr w = sp;
    auto put = [&](std::uint32_t v) {
        *proc.mem.ptr<std::uint32_t>(w) = v;
        w += 4;
    };
    put(static_cast<std::uint32_t>(argv_ptrs.size()));
    for (gaddr p : argv_ptrs) put(p);
    put(0);
    for (gaddr p : env_ptrs) put(p);
    put(0);
    for (std::uint32_t v : aux) put(v);

    gaddr start = has_interp ? interp.entry : exe.entry;
    entry.pc = start & ~gaddr{1};
    entry.thumb = start & 1;
    entry.sp = sp;
    return true;
}

}  // namespace arm32
