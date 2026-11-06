// Guest address space: 4 GB of host address space, guest address g at host base + g.
//
// The whole range is reserved once with no access. Guest mappings make the host pages under them
// readable and writable; protections are kept in the mapping list and in the page table Dynarmic
// reads, not in the host page tables. That keeps guest pages at 4 KB even when the host pages
// are 16 KB, at the cost of not trapping guest writes to read-only pages (Android code does not
// rely on that). With host_guards (fastmem), a host page whose guest pages are all PROT_NONE is
// closed on the host as well, so guard pages still fault.
#include "runtime.h"

#include <algorithm>
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>

namespace arm32 {

namespace {
// Where mmap places mappings without a usable hint: top-down below the stack, as on 32-bit ARM Linux.
constexpr gaddr kMmapTop = 0xbe000000;
// Nothing is placed below this unless asked for by address: null-pointer accesses always fault,
// and no guest buffer can be taken for a GL buffer offset by the graphics bridge.
constexpr gaddr kMmapBottom = kLowestGuestPointer;
// The 4 GB guest range plus slack, so host page rounding never reaches outside the reservation.
constexpr std::size_t kReserve = (std::size_t{1} << 32) + (std::size_t{1} << 20);
// One past a mapping's last byte; a mapping that reaches the top of the 4 GB has end 0.
std::uint64_t end_of(const Vma& v) { return v.end ? v.end : std::uint64_t{1} << 32; }
}  // namespace

bool Memory::init() {
    // The host page size decides the granularity at which host memory can be made accessible.
    host_page_ = static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
    // Reserve the whole guest range without committing memory; pages become accessible on demand.
    void* p = mmap(nullptr, kReserve, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) {
        log("arm32: cannot reserve 4 GB of address space: %s", strerror(errno));
        return false;
    }
    base_ = static_cast<std::uint8_t*>(p);
    // Every guest page starts unmapped: a null entry makes Dynarmic call back instead of reading.
    page_table_ = std::make_unique<std::array<std::uint8_t*, kPageCount>>();
    page_table_->fill(nullptr);
    // One state per host page of the reservation, all released to begin with.
    committed_.assign(kReserve / host_page_, kHostReleased);
    return true;
}

std::int64_t Memory::find_free(gaddr hint, std::uint32_t length) const {
    // A hint is honoured when the whole range is free, as Linux does.
    if (hint >= kMmapBottom && std::uint64_t{hint} + length <= kMmapTop) {
        auto next = vmas_.lower_bound(hint);
        bool clear = next == vmas_.end() || next->first >= hint + length;
        if (clear && next != vmas_.begin()) {
            auto prev = std::prev(next);
            clear = prev->second.end <= hint;
        }
        if (clear) return hint;
    }
    // Otherwise take the highest gap below kMmapTop that fits, walking the mappings downwards.
    std::uint64_t top = kMmapTop;
    auto it = vmas_.lower_bound(kMmapTop);
    while (true) {
        // The gap below `top` reaches down to the end of the previous mapping (or the bottom).
        std::uint64_t floor = kMmapBottom;
        if (it != vmas_.begin()) {
            auto prev = std::prev(it);
            floor = std::max<std::uint64_t>(floor, prev->second.end);
            // A mapping that straddles kMmapTop leaves no gap above it.
            if (prev->second.end > top) floor = top;
        }
        if (top >= floor + length) return static_cast<std::int64_t>(top - length);
        if (it == vmas_.begin()) break;
        --it;
        top = it->first;
        if (top <= kMmapBottom) break;
    }
    return -ENOMEM;
}

void Memory::set_host(std::size_t first, std::size_t last, int prot, std::uint8_t state) {
    mprotect(base_ + first * host_page_, (last - first) * host_page_, prot);
    std::fill(committed_.begin() + static_cast<std::ptrdiff_t>(first), committed_.begin() + static_cast<std::ptrdiff_t>(last), state);
}

void Memory::commit(gaddr start, gaddr end) {
    // Open every host page under [start, end) that is not open yet, in contiguous runs: released
    // pages come back reading as zero, closed ones keep their contents.
    std::size_t first = start / host_page_;
    std::size_t last = (std::uint64_t{end} + host_page_ - 1) / host_page_;
    std::size_t run = first;
    for (std::size_t hp = first; hp <= last; ++hp) {
        bool stop = hp == last || committed_[hp] == kHostOpen;
        if (stop && run < hp) set_host(run, hp, PROT_READ | PROT_WRITE, kHostOpen);
        if (stop) run = hp + 1;
    }
}

bool Memory::host_page_in_use(std::size_t hp) const {
    // Is any part of this host page still mapped by the guest? The mapping that starts last at or
    // before the page's end is the only one that can reach into it.
    std::uint64_t hp_start = std::uint64_t{hp} * host_page_;
    std::uint64_t hp_end = hp_start + host_page_;
    auto it = vmas_.upper_bound(static_cast<gaddr>(std::min<std::uint64_t>(hp_end - 1, 0xffffffffu)));
    if (it == vmas_.begin()) return false;
    --it;
    return end_of(it->second) > hp_start;
}

void Memory::release(gaddr start, gaddr end) {
    // The guest pages must read as zero if mapped again. Host pages no mapping uses any more are
    // given back in contiguous runs, two system calls a run rather than a host page (a 4 MB
    // munmap was 2048 of them); parts of host pages still shared with another mapping are cleared
    // by hand.
    std::size_t first = start / host_page_;
    std::size_t last = (std::uint64_t{end} + host_page_ - 1) / host_page_;
    std::size_t run = first;
    bool in_run = false;
    auto give_back = [&](std::size_t to) {
        if (!in_run) return;
        madvise(base_ + run * host_page_, (to - run) * host_page_, MADV_DONTNEED);
        set_host(run, to, PROT_NONE, kHostReleased);
        in_run = false;
    };
    for (std::size_t hp = first; hp < last; ++hp) {
        if (committed_[hp] == kHostReleased) {
            give_back(hp);
            continue;
        }
        if (!host_page_in_use(hp)) {
            if (!in_run) run = hp;
            in_run = true;
            continue;
        }
        give_back(hp);
        // Shared: clear only the guest pages of this host page that were released, opening it
        // first when the guest pages left in it are all PROT_NONE (closed).
        if (committed_[hp] == kHostClosed) set_host(hp, hp + 1, PROT_READ | PROT_WRITE, kHostOpen);
        std::uint64_t hp_start = std::uint64_t{hp} * host_page_;
        std::uint64_t a = std::max<std::uint64_t>(hp_start, start);
        std::uint64_t b = std::min<std::uint64_t>(hp_start + host_page_, end);
        if (a < b) std::memset(base_ + a, 0, b - a);
    }
    give_back(last);
}

void Memory::sync_host_access(gaddr start, gaddr end) {
    if (!host_guards || std::uint64_t{end} <= start) return;
    // A host page is open when any of its guest pages is accessible (a non-null page table
    // entry), closed when none is. Changes go out as runs, one mprotect each.
    const std::size_t per = host_page_ / kPageSize;
    std::size_t first = start / host_page_;
    std::size_t last = (std::uint64_t{end} + host_page_ - 1) / host_page_;
    std::size_t run = first;
    std::uint8_t run_state = kHostReleased;  // no run
    auto flush = [&](std::size_t to) {
        if (run_state == kHostOpen) set_host(run, to, PROT_READ | PROT_WRITE, kHostOpen);
        if (run_state == kHostClosed) set_host(run, to, PROT_NONE, kHostClosed);
        run_state = kHostReleased;
    };
    for (std::size_t hp = first; hp < last; ++hp) {
        std::uint8_t want = kHostReleased;  // released pages stay as they are
        if (committed_[hp] != kHostReleased) {
            want = kHostClosed;
            for (std::size_t i = 0; i < per; ++i) {
                std::size_t gp = hp * per + i;
                if (gp < kPageCount && (*page_table_)[gp]) {
                    want = kHostOpen;
                    break;
                }
            }
            if (want == committed_[hp]) want = kHostReleased;  // already right
        }
        if (want != run_state) {
            flush(hp);
            run = hp;
            run_state = want;
        }
    }
    flush(last);
}

void Memory::set_access(gaddr start, gaddr end, bool accessible) {
    // Absolute-offset page table: the entry is the host base for every accessible page.
    for (std::uint64_t page = start >> kPageShift; page < (std::uint64_t{end} + kPageSize - 1) >> kPageShift; ++page) {
        (*page_table_)[page] = accessible ? base_ : nullptr;
    }
}

void Memory::insert(gaddr start, Vma vma) {
    vmas_[start] = std::move(vma);
}

void Memory::erase(gaddr start, gaddr end) {
    // Remove [start, end) from the mapping list, keeping the parts of mappings outside it.
    auto it = vmas_.lower_bound(start);
    if (it != vmas_.begin()) {
        auto prev = std::prev(it);
        if (prev->second.end > start) it = prev;
    }
    std::vector<std::pair<gaddr, Vma>> keep;
    while (it != vmas_.end() && it->first < end) {
        gaddr vstart = it->first;
        Vma v = it->second;
        it = vmas_.erase(it);
        // Left remainder.
        if (vstart < start) {
            Vma left = v;
            left.end = start;
            keep.emplace_back(vstart, left);
        }
        // Right remainder, with its file offset moved along.
        if (v.end > end) {
            Vma right = v;
            right.offset = v.offset + (end - vstart);
            keep.emplace_back(end, right);
        }
    }
    for (auto& [s, v] : keep) vmas_[s] = v;
}

std::int64_t Memory::map(gaddr hint, std::uint32_t length, int prot, bool fixed, const std::string& name, std::uint64_t offset) {
    std::lock_guard<std::recursive_mutex> g(lock_);
    std::uint64_t len = page_up(length);
    if (len == 0 || len > 0xffffffffull) return -EINVAL;
    std::int64_t start;
    if (fixed) {
        // MAP_FIXED: the range must be page aligned and is replaced, contents and all.
        if (hint & (kPageSize - 1)) return -EINVAL;
        if (std::uint64_t{hint} + len > (std::uint64_t{1} << 32)) return -ENOMEM;
        start = hint;
        erase(hint, static_cast<gaddr>(hint + len));
        set_access(hint, static_cast<gaddr>(hint + len), false);
        release(hint, static_cast<gaddr>(hint + len));
    } else {
        start = find_free(static_cast<gaddr>(page_down(hint)), static_cast<std::uint32_t>(len));
        if (start < 0) return start;
    }
    gaddr s = static_cast<gaddr>(start);
    gaddr e = static_cast<gaddr>(s + len);
    insert(s, Vma{e, prot, name, offset});
    commit(s, e);
    set_access(s, e, prot != 0);
    sync_host_access(s, e);
    // Code may have lived here before.
    if (on_code_change) on_code_change(s, static_cast<std::uint32_t>(len));
    return s;
}

int Memory::unmap(gaddr addr, std::uint32_t length) {
    std::lock_guard<std::recursive_mutex> g(lock_);
    if (addr & (kPageSize - 1)) return -EINVAL;
    std::uint64_t len = page_up(length);
    if (len == 0) return -EINVAL;
    gaddr end = static_cast<gaddr>(std::min<std::uint64_t>(std::uint64_t{addr} + len, 0xfffff000ull));
    if (end <= addr) return 0;
    erase(addr, end);
    set_access(addr, end, false);
    release(addr, end);
    // A host page shared with what is left may now hold only PROT_NONE pages.
    sync_host_access(addr, end);
    if (on_code_change) on_code_change(addr, end - addr);
    return 0;
}

int Memory::protect(gaddr addr, std::uint32_t length, int prot) {
    std::lock_guard<std::recursive_mutex> g(lock_);
    if (addr & (kPageSize - 1)) return -EINVAL;
    // No pages: nothing changes (as on Linux). The splitting below would otherwise cut the
    // mapping at addr and put an empty one there, losing the rest of it from the list.
    if (length == 0) return 0;
    std::uint64_t end64 = std::uint64_t{addr} + page_up(length);
    if (end64 > (std::uint64_t{1} << 32)) return -ENOMEM;
    gaddr end = static_cast<gaddr>(end64);
    // Every page in the range must be mapped, as for the real mprotect.
    for (std::uint64_t p = addr; p < end64; p += kPageSize) {
        auto it = vmas_.upper_bound(static_cast<gaddr>(p));
        if (it == vmas_.begin() || end_of(std::prev(it)->second) <= p) return -ENOMEM;
    }
    // Split the mappings at the range edges and set the new protection inside.
    std::vector<std::pair<gaddr, Vma>> pieces;
    auto it = vmas_.upper_bound(addr);
    --it;
    while (it != vmas_.end() && it->first < end) {
        pieces.emplace_back(it->first, it->second);
        ++it;
    }
    erase(addr, end);
    for (auto& [s, v] : pieces) {
        gaddr a = std::max(s, addr);
        gaddr b = std::min(v.end, end);
        Vma inner = v;
        inner.end = b;
        inner.prot = prot;
        inner.offset = v.offset + (a - s);
        insert(a, inner);
    }
    set_access(addr, end, prot != 0);
    sync_host_access(addr, end);
    if ((prot & kProtExec) && on_code_change) on_code_change(addr, end - addr);
    return 0;
}

std::int64_t Memory::remap(gaddr old_addr, std::uint32_t old_len, std::uint32_t new_len, bool may_move) {
    std::lock_guard<std::recursive_mutex> g(lock_);
    std::uint64_t olen = page_up(old_len), nlen = page_up(new_len);
    if (old_addr & (kPageSize - 1) || nlen == 0 || nlen > 0xfffff000ull) return -EINVAL;
    // The old range must lie inside one mapping, as Linux requires; it may be only part of it.
    auto it = vmas_.upper_bound(old_addr);
    if (it == vmas_.begin()) return -EFAULT;
    --it;
    const gaddr vstart = it->first;
    const Vma v = it->second;
    const std::uint64_t old_end = std::uint64_t{old_addr} + olen;
    if (old_end > end_of(v)) return -EFAULT;
    // Shrinking: drop the tail.
    if (nlen <= olen) {
        if (nlen < olen) unmap(static_cast<gaddr>(old_addr + nlen), static_cast<std::uint32_t>(olen - nlen));
        return old_addr;
    }
    // Growing in place: only when the range ends where its mapping ends and the pages after it
    // are free. (Growing the start of a larger mapping in place would take over pages that are
    // still the mapping's own and drop them from the list while they stay in use.)
    const std::uint64_t new_end = std::uint64_t{old_addr} + nlen;
    if (old_end == end_of(v)) {
        auto next = std::next(it);
        bool room = new_end <= kMmapTop && (next == vmas_.end() || next->first >= new_end);
        if (room) {
            it->second.end = static_cast<gaddr>(new_end);
            commit(static_cast<gaddr>(old_end), static_cast<gaddr>(new_end));
            set_access(static_cast<gaddr>(old_end), static_cast<gaddr>(new_end), v.prot != 0);
            sync_host_access(static_cast<gaddr>(old_end), static_cast<gaddr>(new_end));
            return old_addr;
        }
    }
    if (!may_move) return -ENOMEM;
    // Moving: a new mapping with the same protection and name, the pages copied over, the old
    // range unmapped (the rest of a larger mapping stays where it is).
    std::int64_t dst = find_free(0, static_cast<std::uint32_t>(nlen));
    if (dst < 0) return dst;
    gaddr d = static_cast<gaddr>(dst);
    insert(d, Vma{static_cast<gaddr>(d + nlen), v.prot, v.name, v.offset + (old_addr - vstart)});
    commit(d, static_cast<gaddr>(d + nlen));
    // A PROT_NONE source may be closed on the host: open it for the copy (it is unmapped next).
    commit(old_addr, static_cast<gaddr>(old_end));
    std::memcpy(base_ + d, base_ + old_addr, olen);
    set_access(d, static_cast<gaddr>(d + nlen), v.prot != 0);
    sync_host_access(d, static_cast<gaddr>(d + nlen));
    unmap(old_addr, static_cast<std::uint32_t>(olen));
    return d;
}

bool Memory::mapped(gaddr addr, std::uint32_t length) const {
    std::lock_guard<std::recursive_mutex> g(lock_);
    std::uint64_t p = page_down(addr);
    const std::uint64_t end = std::uint64_t{addr} + length;
    if (end > (std::uint64_t{1} << 32)) return false;
    // Walk the mappings that cover the range one after another; a gap ends the walk.
    while (p < end) {
        auto it = vmas_.upper_bound(static_cast<gaddr>(p));
        if (it == vmas_.begin()) return false;
        --it;
        if (end_of(it->second) <= p) return false;
        p = end_of(it->second);
    }
    return true;
}

int Memory::discard(gaddr addr, std::uint32_t length) {
    std::lock_guard<std::recursive_mutex> g(lock_);
    if (addr & (kPageSize - 1)) return -EINVAL;
    const std::uint64_t end = std::uint64_t{addr} + page_up(length);
    if (end > (std::uint64_t{1} << 32)) return -EINVAL;
    if (!mapped(addr, static_cast<std::uint32_t>(end - addr))) return -ENOMEM;
    // Mapping by mapping: anonymous memory reads as zero afterwards; a private file mapping keeps
    // what it holds, the file's contents unless the guest wrote to its copy (Linux would read the
    // file again, which zeroing here would not do either).
    for (std::uint64_t p = addr; p < end;) {
        auto it = std::prev(vmas_.upper_bound(static_cast<gaddr>(p)));
        const std::uint64_t to = std::min(end, end_of(it->second));
        const std::string& name = it->second.name;
        if (name.empty() || name[0] == '[') {
            // Whole host pages go back to the system (they read as zero from then on); the guest
            // pages of a host page shared with other memory are cleared by hand.
            std::uint64_t first = (p + host_page_ - 1) / host_page_ * host_page_;
            std::uint64_t last = to / host_page_ * host_page_;
            if (first < last) {
                madvise(base_ + first, last - first, MADV_DONTNEED);
            } else {
                first = last = to;
            }
            for (auto [a, b] : {std::pair<std::uint64_t, std::uint64_t>{p, first}, {last, to}}) {
                if (a >= b) continue;
                std::size_t hp = a / host_page_;
                if (committed_[hp] == kHostClosed) set_host(hp, hp + 1, PROT_READ | PROT_WRITE, kHostOpen);
                std::memset(base_ + a, 0, b - a);
            }
        }
        p = to;
    }
    // Pages opened for clearing close again when all their guest pages are PROT_NONE.
    sync_host_access(addr, static_cast<gaddr>(end));
    return 0;
}

bool Memory::readable(gaddr addr, std::uint32_t length) const {
    if (length == 0) return true;
    std::uint64_t end = std::uint64_t{addr} + length;
    if (end > (std::uint64_t{1} << 32)) return false;
    for (std::uint64_t p = addr >> kPageShift; p < (end + kPageSize - 1) >> kPageShift; ++p) {
        if (!(*page_table_)[p]) return false;
    }
    return true;
}

bool Memory::constant_code(gaddr addr, std::uint32_t length) const {
    std::lock_guard<std::recursive_mutex> g(lock_);
    auto it = vmas_.upper_bound(addr);
    if (it == vmas_.begin()) return false;
    --it;
    const Vma& v = it->second;
    // Inside one mapping, readable and executable but not writable, and backed by a file (the
    // labels of anonymous mappings start with '[').
    return std::uint64_t{addr} + length <= v.end && (v.prot & kProtRead) && (v.prot & kProtExec) && !(v.prot & kProtWrite) &&
           !v.name.empty() && v.name[0] != '[';
}

std::string Memory::code_location(gaddr addr) const {
    std::lock_guard<std::recursive_mutex> g(lock_);
    // The mapping that starts at or below addr, if addr lies inside it.
    auto it = vmas_.upper_bound(addr);
    if (it == vmas_.begin()) return {};
    --it;
    const Vma& v = it->second;
    if (addr >= v.end || !(v.prot & kProtExec)) return {};
    // File name without the folder, and the offset in the file (which for the first segment of
    // a library is also the address readelf and objdump use).
    std::string file = v.name.empty() ? "anon" : v.name.substr(v.name.rfind('/') + 1);
    char off[24];
    std::snprintf(off, sizeof off, "+%#llx", static_cast<unsigned long long>(addr - it->first + v.offset));
    return file + off;
}

std::string Memory::maps_text() const {
    std::lock_guard<std::recursive_mutex> g(lock_);
    // Same columns as Linux: range, permissions, offset, device, inode, name.
    std::string out;
    char line[512];
    for (auto& [start, v] : vmas_) {
        std::snprintf(line, sizeof line, "%08x-%08x %c%c%cp %08" PRIx64 " 00:00 0          %s\n", start, v.end,
                      (v.prot & kProtRead) ? 'r' : '-', (v.prot & kProtWrite) ? 'w' : '-', (v.prot & kProtExec) ? 'x' : '-',
                      v.offset, v.name.c_str());
        out += line;
    }
    return out;
}

}  // namespace arm32
