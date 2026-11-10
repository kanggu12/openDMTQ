// Descriptors on Windows (layer.h): the table, files and directories on Win32 handles with Linux's meaning (an offset of
// the descriptor's own, so pread leaves it alone; deleting and renaming open files), pipes, eventfd and memfd inside the
// process, the devices the guest opens (/dev/null, /dev/zero, /dev/urandom), and the waits on any of them: poll, select
// and epoll.
#include "layer.h"

#include <psapi.h>

#include <algorithm>
#include <climits>
#include <cstring>
#include <deque>
#include <map>
#include <unordered_map>
#include <unordered_set>

namespace arm32::win {

// ---------------------------------------------------------------------------------------------------------------------
// What every kind does unless it says otherwise.

ssize_t Fd::read(void*, std::size_t) { return fail(EINVAL); }
ssize_t Fd::write(const void*, std::size_t) { return fail(EINVAL); }
ssize_t Fd::pread(void*, std::size_t, long long) { return fail(ESPIPE); }
ssize_t Fd::pwrite(const void*, std::size_t, long long) { return fail(ESPIPE); }
long long Fd::seek(long long, int) { return fail(ESPIPE); }
int Fd::stat(struct stat* st) {
    std::memset(st, 0, sizeof *st);
    st->st_mode = S_IFIFO | 0600;
    st->st_blksize = 4096;
    return 0;
}
int Fd::truncate(long long) { return fail(EINVAL); }
int Fd::sync() { return 0; }
short Fd::ready(short events) { return static_cast<short>(events & (POLLIN | POLLOUT)); }

// ---------------------------------------------------------------------------------------------------------------------
// The table.

namespace {

struct Slot {
    std::shared_ptr<Fd> fd;
    bool cloexec = false;
};

// The process's standard input, output and error: Windows' own handles behind descriptors 0, 1 and 2, as a Linux
// process starts with them taken, so that the first file opened gets 3.
class Standard : public Fd {
public:
    explicit Standard(DWORD which) : which_(which) {}
    ssize_t read(void* buf, std::size_t n) override {
        DWORD got = 0;
        if (!ReadFile(GetStdHandle(which_), buf, static_cast<DWORD>(std::min<std::size_t>(n, 0x7ffff000)), &got, nullptr)) {
            // A closed input reads as its end.
            if (GetLastError() == ERROR_BROKEN_PIPE || GetLastError() == ERROR_HANDLE_EOF) return 0;
            return fail_win32();
        }
        return static_cast<ssize_t>(got);
    }
    ssize_t write(const void* buf, std::size_t n) override {
        DWORD put = 0;
        if (!WriteFile(GetStdHandle(which_), buf, static_cast<DWORD>(std::min<std::size_t>(n, 0x7ffff000)), &put, nullptr)) return fail_win32();
        return static_cast<ssize_t>(put);
    }
    int stat(struct stat* st) override {
        std::memset(st, 0, sizeof *st);
        st->st_mode = S_IFCHR | 0620;
        st->st_blksize = 4096;
        return 0;
    }

private:
    DWORD which_;
};

std::mutex g_table_lock;
std::vector<Slot>& table() {
    static auto* t = [] {
        auto* v = new std::vector<Slot>(4096);
        (*v)[0].fd = std::make_shared<Standard>(STD_INPUT_HANDLE);
        (*v)[1].fd = std::make_shared<Standard>(STD_OUTPUT_HANDLE);
        (*v)[2].fd = std::make_shared<Standard>(STD_ERROR_HANDLE);
        return v;
    }();
    return *t;
}

}  // namespace

int fd_add(std::shared_ptr<Fd> f, bool cloexec, int at_least) {
    std::lock_guard<std::mutex> l(g_table_lock);
    auto& t = table();
    for (std::size_t i = static_cast<std::size_t>(std::max(at_least, 0)); i < t.size(); ++i) {
        if (!t[i].fd) {
            t[i] = Slot{std::move(f), cloexec};
            return static_cast<int>(i);
        }
    }
    return fail(EMFILE);
}

std::shared_ptr<Fd> fd_get(int fd) {
    std::lock_guard<std::mutex> l(g_table_lock);
    if (fd < 0 || static_cast<std::size_t>(fd) >= table().size()) return nullptr;
    return table()[static_cast<std::size_t>(fd)].fd;
}

int fd_put(int fd, std::shared_ptr<Fd> f, bool cloexec) {
    std::shared_ptr<Fd> old;
    {
        std::lock_guard<std::mutex> l(g_table_lock);
        if (fd < 0 || static_cast<std::size_t>(fd) >= table().size()) return fail(EBADF);
        old = std::move(table()[static_cast<std::size_t>(fd)].fd);
        table()[static_cast<std::size_t>(fd)] = Slot{std::move(f), cloexec};
    }
    // What was there closes outside the lock: closing may wake others. Whoever waits on it looks again, as fd_close's.
    if (old) old->notify();
    return fd;
}

int fd_close(int fd) {
    std::shared_ptr<Fd> old;
    {
        std::lock_guard<std::mutex> l(g_table_lock);
        if (fd < 0 || static_cast<std::size_t>(fd) >= table().size() || !table()[static_cast<std::size_t>(fd)].fd) return fail(EBADF);
        old = std::move(table()[static_cast<std::size_t>(fd)].fd);
        table()[static_cast<std::size_t>(fd)].cloexec = false;
    }
    // Whoever waits on it looks again, and lets it go if it was the last: an epoll wait holds what it watches while it
    // sleeps (Linux's holds nothing), and a pipe's other end sees its end only once this one goes.
    old->notify();
    return 0;
}

bool fd_cloexec(int fd) {
    std::lock_guard<std::mutex> l(g_table_lock);
    return fd >= 0 && static_cast<std::size_t>(fd) < table().size() && table()[static_cast<std::size_t>(fd)].cloexec;
}

void fd_set_cloexec(int fd, bool on) {
    std::lock_guard<std::mutex> l(g_table_lock);
    if (fd >= 0 && static_cast<std::size_t>(fd) < table().size()) table()[static_cast<std::size_t>(fd)].cloexec = on;
}

namespace {

// ---------------------------------------------------------------------------------------------------------------------
// Files: a Win32 handle and the descriptor's own offset (every read and write says where, so that pread and pwrite
// leave the offset as Linux does, and dup'd descriptors share it).

long long filetime_ns(const FILETIME& ft) {
    // FILETIME counts 100 ns from 1601; Unix time from 1970.
    return ((static_cast<long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime) - 116444736000000000LL) * 100;
}

// The device number of files on a volume without a serial number (some FAT and network drives, and Wine's drives onto
// the Unix file system have none): 0 would tell Linux programs that the file has no identity to compare, and Android's
// linker would then load one library twice under two of its names.
constexpr std::uint32_t kNoSerialDevice = 0x6e6f7365;

void fill_stat(const BY_HANDLE_FILE_INFORMATION& info, struct stat* st) {
    std::memset(st, 0, sizeof *st);
    // The volume names the device, as the file's index names the file on it.
    st->st_dev = info.dwVolumeSerialNumber ? info.dwVolumeSerialNumber : kNoSerialDevice;
    // NTFS's file index: the record number in the low 48 bits, and how often that record was used in the high 16. The
    // record alone tells files that exist apart, and fits the 32-bit inode of a 32-bit program's old stat call, which
    // the index with its count would overflow.
    st->st_ino = (static_cast<std::uint64_t>(info.nFileIndexHigh) << 32 | info.nFileIndexLow) & 0xffffffffffffull;
    st->st_nlink = info.nNumberOfLinks;
    bool dir = info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY;
    bool readonly = info.dwFileAttributes & FILE_ATTRIBUTE_READONLY;
    st->st_mode = dir ? (S_IFDIR | 0755) : (S_IFREG | (readonly ? 0444 : 0644));
    st->st_uid = st->st_gid = 10000;
    st->st_size = static_cast<long long>(info.nFileSizeHigh) << 32 | info.nFileSizeLow;
    st->st_blksize = 4096;
    st->st_blocks = (st->st_size + 511) / 512;
    auto ts = [](long long ns, struct timespec& t) {
        t.tv_sec = static_cast<time_t>(ns / 1000000000LL);
        t.tv_nsec = static_cast<long>(ns % 1000000000LL);
    };
    ts(filetime_ns(info.ftLastAccessTime), st->st_atim);
    ts(filetime_ns(info.ftLastWriteTime), st->st_mtim);
    ts(filetime_ns(info.ftLastWriteTime), st->st_ctim);
}

// The process's appends (O_APPEND), one at a time: Windows writes each at the end of its file in one step, which
// another program's append cannot come between, and Wine in two (the end looked up, then a write there), which another
// thread's could.
std::mutex g_append_lock;

class File : public Fd {
public:
    explicit File(HANDLE h) : h_(h) {}
    ~File() override { CloseHandle(h_); }
    HANDLE handle() const { return h_; }
    ssize_t read(void* buf, std::size_t n) override {
        std::lock_guard<std::mutex> l(lock_);
        ssize_t r = pread(buf, n, pos_);
        if (r > 0) pos_ += r;
        return r;
    }
    ssize_t write(const void* buf, std::size_t n) override {
        std::lock_guard<std::mutex> l(lock_);
        if (status_flags.load() & O_APPEND) {
            // O_APPEND: at the end, wherever another descriptor or program has taken it, as Linux's is; the offset then
            // after what it wrote.
            std::lock_guard<std::mutex> a(g_append_lock);
            ssize_t r = write_at(buf, n, kAtTheEnd);
            LARGE_INTEGER size;
            if (r >= 0 && GetFileSizeEx(h_, &size)) pos_ = size.QuadPart;
            return r;
        }
        ssize_t r = write_at(buf, n, pos_);
        if (r > 0) pos_ += r;
        return r;
    }
    ssize_t pread(void* buf, std::size_t n, long long offset) override {
        OVERLAPPED ov{};
        ov.Offset = static_cast<DWORD>(offset);
        ov.OffsetHigh = static_cast<DWORD>(offset >> 32);
        DWORD got = 0;
        if (!ReadFile(h_, buf, static_cast<DWORD>(std::min<std::size_t>(n, 0x7ffff000)), &got, &ov)) {
            // Past the end: nothing more, as Linux says by reading nothing.
            if (GetLastError() == ERROR_HANDLE_EOF) return 0;
            return fail_win32();
        }
        return static_cast<ssize_t>(got);
    }
    ssize_t pwrite(const void* buf, std::size_t n, long long offset) override {
        if (status_flags.load() & O_APPEND) {
            // At the end whatever the offset, as Linux's pwrite writes with O_APPEND.
            std::lock_guard<std::mutex> a(g_append_lock);
            return write_at(buf, n, kAtTheEnd);
        }
        return write_at(buf, n, offset);
    }
    long long seek(long long offset, int whence) override {
        std::lock_guard<std::mutex> l(lock_);
        long long base = 0;
        if (whence == SEEK_CUR) base = pos_;
        else if (whence == SEEK_END) {
            LARGE_INTEGER size;
            if (!GetFileSizeEx(h_, &size)) return fail_win32();
            base = size.QuadPart;
        } else if (whence != SEEK_SET) {
            return fail(EINVAL);
        }
        if (base + offset < 0) return fail(EINVAL);
        pos_ = base + offset;
        return pos_;
    }
    int stat(struct stat* st) override {
        BY_HANDLE_FILE_INFORMATION info;
        if (!GetFileInformationByHandle(h_, &info)) return fail_win32();
        fill_stat(info, st);
        return 0;
    }
    int truncate(long long size) override {
        FILE_END_OF_FILE_INFO eof;
        eof.EndOfFile.QuadPart = size;
        if (!SetFileInformationByHandle(h_, FileEndOfFileInfo, &eof, sizeof eof)) return fail_win32();
        return 0;
    }
    int sync() override { return FlushFileBuffers(h_) ? 0 : fail_win32(); }
    // A regular file is always ready; what a read would get is the rest from the offset.
    long bytes_ready() override {
        std::lock_guard<std::mutex> l(lock_);
        LARGE_INTEGER size;
        if (!GetFileSizeEx(h_, &size) || size.QuadPart <= pos_) return 0;
        return static_cast<long>(std::min<long long>(size.QuadPart - pos_, LONG_MAX));
    }

private:
    // Windows' offset of all ones: the file's end.
    static constexpr long long kAtTheEnd = -1;
    ssize_t write_at(const void* buf, std::size_t n, long long offset) {
        OVERLAPPED ov{};
        ov.Offset = static_cast<DWORD>(offset);
        ov.OffsetHigh = static_cast<DWORD>(offset >> 32);
        DWORD put = 0;
        if (!WriteFile(h_, buf, static_cast<DWORD>(std::min<std::size_t>(n, 0x7ffff000)), &put, &ov)) return fail_win32();
        return static_cast<ssize_t>(put);
    }
    HANDLE h_;
    std::mutex lock_;
    long long pos_ = 0;
};

// A directory: its handle (for fstat) and its path, whose entries getdents64 lists.
class Dir : public File {
public:
    Dir(HANDLE h, std::wstring path) : File(h), path_(std::move(path)) {}
    ~Dir() override {
        if (find_ != INVALID_HANDLE_VALUE) FindClose(find_);
    }
    ssize_t read(void*, std::size_t) override { return fail(EISDIR); }
    ssize_t write(const void*, std::size_t) override { return fail(EISDIR); }
    long bytes_ready() override { return 0; }
    // A place in the listing: the number of entries before it, which each entry's d_off gives (telldir), and 0 its
    // start (rewinddir). The listing starts again and skips that many.
    long long seek(long long offset, int whence) override {
        std::lock_guard<std::mutex> l(lock_);
        // Where the listing is, unmoved.
        if (whence == SEEK_CUR && offset == 0) return static_cast<long long>(index_);
        if (whence != SEEK_SET || offset < 0) return fail(EINVAL);
        if (find_ != INVALID_HANDLE_VALUE) FindClose(find_);
        find_ = INVALID_HANDLE_VALUE;
        have_ = done_ = false;
        index_ = 0;
        while (index_ < static_cast<std::uint64_t>(offset) && next()) {
            // Skipped: as if read before.
            have_ = false;
            ++index_;
        }
        return static_cast<long long>(index_);
    }
    // Entries as linux_dirent64 records, as many as fit; 0 at the end.
    long entries(void* buf, std::size_t n) {
        std::lock_guard<std::mutex> l(lock_);
        auto* out = static_cast<std::uint8_t*>(buf);
        std::size_t used = 0;
        while (next()) {
            std::string name = narrow(data_.cFileName);
            std::size_t reclen = (offsetof(linux_dirent64, d_name) + name.size() + 1 + 7) & ~std::size_t{7};
            if (used + reclen > n) {
                // Not even one fits: the caller's buffer is too small.
                if (used == 0) return fail(EINVAL);
                break;
            }
            auto* d = reinterpret_cast<linux_dirent64*>(out + used);
            d->d_ino = ++index_;
            d->d_off = static_cast<std::int64_t>(index_);
            d->d_reclen = static_cast<unsigned short>(reclen);
            d->d_type = (data_.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? DT_DIR : DT_REG;
            std::memcpy(d->d_name, name.c_str(), name.size() + 1);
            used += reclen;
            have_ = false;
        }
        return static_cast<long>(used);
    }

private:
    // The entry to give next in data_, found if it is not there yet; false at the end. Under the lock.
    bool next() {
        if (have_) return true;
        if (done_) return false;
        if (find_ == INVALID_HANDLE_VALUE) {
            find_ = FindFirstFileW((path_ + L"\\*").c_str(), &data_);
            if (find_ == INVALID_HANDLE_VALUE) {
                done_ = true;
                return false;
            }
        } else if (!FindNextFileW(find_, &data_)) {
            done_ = true;
            return false;
        }
        have_ = true;
        return true;
    }
    std::wstring path_;
    std::mutex lock_;
    HANDLE find_ = INVALID_HANDLE_VALUE;
    WIN32_FIND_DATAW data_{};
    bool have_ = false, done_ = false;
    std::uint64_t index_ = 0;
};

// /dev/null, /dev/zero, /dev/urandom and /dev/random.
class Device : public Fd {
public:
    enum Kind { kNull, kZero, kRandom };
    explicit Device(Kind k) : kind_(k) {}
    ssize_t read(void* buf, std::size_t n) override {
        if (kind_ == kNull) return 0;
        if (kind_ == kZero) {
            std::memset(buf, 0, n);
            return static_cast<ssize_t>(n);
        }
        return static_cast<ssize_t>(arm32::posix::syscall(__NR_getrandom, buf, n, 0));
    }
    ssize_t write(const void*, std::size_t n) override { return static_cast<ssize_t>(n); }
    int stat(struct stat* st) override {
        std::memset(st, 0, sizeof *st);
        st->st_mode = S_IFCHR | 0666;
        st->st_rdev = kind_ == kNull ? 0x103 : kind_ == kZero ? 0x105 : 0x109;
        st->st_blksize = 4096;
        return 0;
    }

private:
    Kind kind_;
};

// An in-memory file: memfd_create's.
class Memfd : public Fd {
public:
    ssize_t read(void* buf, std::size_t n) override {
        std::lock_guard<std::mutex> l(lock_);
        ssize_t r = read_at(buf, n, pos_);
        pos_ += r;
        return r;
    }
    ssize_t write(const void* buf, std::size_t n) override {
        std::lock_guard<std::mutex> l(lock_);
        ssize_t r = write_at(buf, n, pos_);
        pos_ += r;
        return r;
    }
    ssize_t pread(void* buf, std::size_t n, long long offset) override {
        std::lock_guard<std::mutex> l(lock_);
        return read_at(buf, n, offset);
    }
    ssize_t pwrite(const void* buf, std::size_t n, long long offset) override {
        std::lock_guard<std::mutex> l(lock_);
        return write_at(buf, n, offset);
    }
    long long seek(long long offset, int whence) override {
        std::lock_guard<std::mutex> l(lock_);
        long long base = whence == SEEK_CUR ? pos_ : whence == SEEK_END ? static_cast<long long>(data_.size()) : 0;
        if (base + offset < 0) return fail(EINVAL);
        pos_ = base + offset;
        return pos_;
    }
    int stat(struct stat* st) override {
        std::lock_guard<std::mutex> l(lock_);
        std::memset(st, 0, sizeof *st);
        // An identity of its own: the property area's check compares it.
        st->st_dev = 0x6d656d;
        st->st_ino = reinterpret_cast<std::uintptr_t>(this);
        st->st_mode = S_IFREG | 0600;
        st->st_nlink = 1;
        st->st_size = static_cast<long long>(data_.size());
        st->st_blksize = 4096;
        return 0;
    }
    int truncate(long long size) override {
        std::lock_guard<std::mutex> l(lock_);
        data_.resize(static_cast<std::size_t>(size));
        return 0;
    }
    // What a read would get: the rest from the offset, as a file's.
    long bytes_ready() override {
        std::lock_guard<std::mutex> l(lock_);
        return pos_ < static_cast<long long>(data_.size()) ? static_cast<long>(std::min<long long>(static_cast<long long>(data_.size()) - pos_, LONG_MAX)) : 0;
    }

private:
    ssize_t read_at(void* buf, std::size_t n, long long offset) {
        if (offset >= static_cast<long long>(data_.size())) return 0;
        std::size_t k = std::min(n, data_.size() - static_cast<std::size_t>(offset));
        std::memcpy(buf, data_.data() + offset, k);
        return static_cast<ssize_t>(k);
    }
    ssize_t write_at(const void* buf, std::size_t n, long long offset) {
        if (static_cast<std::size_t>(offset) + n > data_.size()) data_.resize(static_cast<std::size_t>(offset) + n);
        std::memcpy(data_.data() + offset, buf, n);
        return static_cast<ssize_t>(n);
    }
    std::mutex lock_;
    std::vector<std::uint8_t> data_;
    long long pos_ = 0;
};

// A wait on one object until `ready` holds: interruptible, with the descriptor's own O_NONBLOCK saying not to wait.
template <class Ready>
int wait_on(Fd& f, Ready&& ready) {
    HANDLE ev = thread_event();
    for (;;) {
        // Registered before looking, so a change after the look sets the event.
        f.add_waiter(ev);
        if (ready()) {
            f.remove_waiter(ev);
            return 0;
        }
        if (f.status_flags.load() & O_NONBLOCK) {
            f.remove_waiter(ev);
            return -EAGAIN;
        }
        int r = wait_any(&ev, 1, -1);
        f.remove_waiter(ev);
        if (r < 0) return r;
    }
}

// A pipe: a ring buffer in the process, its two ends descriptors of their own.
struct PipeBuffer {
    std::mutex lock;
    std::deque<std::uint8_t> data;
    bool reader_open = true, writer_open = true;
    static constexpr std::size_t kCapacity = 65536;
    Waitable* reader = nullptr;
    Waitable* writer = nullptr;
};

class PipeEnd : public Fd {
public:
    PipeEnd(std::shared_ptr<PipeBuffer> b, bool reading) : b_(std::move(b)), reading_(reading) {
        std::lock_guard<std::mutex> l(b_->lock);
        (reading_ ? b_->reader : b_->writer) = this;
    }
    // Each end tells the other of a change under the buffer's lock, which an end's closing takes first: the other end
    // cannot go while it is told.
    ~PipeEnd() override {
        std::lock_guard<std::mutex> l(b_->lock);
        (reading_ ? b_->reader_open : b_->writer_open) = false;
        (reading_ ? b_->reader : b_->writer) = nullptr;
        // The other end sees the end (EOF) or a broken pipe.
        if (Waitable* other = reading_ ? b_->writer : b_->reader) other->notify();
    }
    ssize_t read(void* buf, std::size_t n) override {
        if (!reading_) return fail(EBADF);
        // A read of nothing returns at once, as Linux's does on a pipe.
        if (n == 0) return 0;
        for (;;) {
            int r = wait_on(*this, [&] {
                std::lock_guard<std::mutex> l(b_->lock);
                return !b_->data.empty() || !b_->writer_open;
            });
            if (r < 0) return fail(-r);
            std::lock_guard<std::mutex> l(b_->lock);
            if (b_->data.empty()) {
                // Another reader took the bytes first: wait again while the writer is there; its end is the pipe's.
                if (b_->writer_open) continue;
                return 0;
            }
            std::size_t k = std::min(n, b_->data.size());
            std::copy(b_->data.begin(), b_->data.begin() + static_cast<std::ptrdiff_t>(k), static_cast<std::uint8_t*>(buf));
            b_->data.erase(b_->data.begin(), b_->data.begin() + static_cast<std::ptrdiff_t>(k));
            // Room for the writer.
            if (b_->writer) b_->writer->notify();
            return static_cast<ssize_t>(k);
        }
    }
    ssize_t write(const void* buf, std::size_t n) override {
        if (reading_) return fail(EBADF);
        const auto* p = static_cast<const std::uint8_t*>(buf);
        std::size_t done = 0;
        while (done < n) {
            int r = wait_on(*this, [&] {
                std::lock_guard<std::mutex> l(b_->lock);
                return b_->data.size() < PipeBuffer::kCapacity || !b_->reader_open;
            });
            if (r < 0) return done ? static_cast<ssize_t>(done) : fail(-r);
            std::lock_guard<std::mutex> l(b_->lock);
            if (!b_->reader_open) return done ? static_cast<ssize_t>(done) : fail(EPIPE);
            std::size_t k = std::min(n - done, PipeBuffer::kCapacity - b_->data.size());
            b_->data.insert(b_->data.end(), p + done, p + done + k);
            done += k;
            // Something for the reader.
            if (b_->reader) b_->reader->notify();
        }
        return static_cast<ssize_t>(done);
    }
    short ready(short events) override {
        std::lock_guard<std::mutex> l(b_->lock);
        short r = 0;
        if (reading_) {
            if (!b_->data.empty()) r |= POLLIN;
            if (!b_->writer_open) r |= POLLHUP;
        } else {
            if (b_->data.size() < PipeBuffer::kCapacity) r |= POLLOUT;
            if (!b_->reader_open) r |= POLLERR;
        }
        return static_cast<short>(r & (events | POLLHUP | POLLERR));
    }
    // The bytes in the pipe, from either end, as Linux's FIONREAD gives them.
    long bytes_ready() override {
        std::lock_guard<std::mutex> l(b_->lock);
        return static_cast<long>(b_->data.size());
    }

private:
    std::shared_ptr<PipeBuffer> b_;
    bool reading_;
};

// eventfd: a 64-bit counter.
class EventFd : public Fd {
public:
    EventFd(std::uint64_t initial, bool semaphore) : count_(initial), semaphore_(semaphore) {}
    ssize_t read(void* buf, std::size_t n) override {
        if (n < 8) return fail(EINVAL);
        std::uint64_t v;
        for (;;) {
            int r = wait_on(*this, [&] {
                std::lock_guard<std::mutex> l(lock_);
                return count_ > 0;
            });
            if (r < 0) return fail(-r);
            std::lock_guard<std::mutex> l(lock_);
            // Another reader took it first: wait again (or EAGAIN, when the descriptor does not block).
            if (!count_) continue;
            v = semaphore_ ? 1 : count_;
            count_ -= v;
            break;
        }
        notify();
        std::memcpy(buf, &v, 8);
        return 8;
    }
    ssize_t write(const void* buf, std::size_t n) override {
        if (n < 8) return fail(EINVAL);
        std::uint64_t v;
        std::memcpy(&v, buf, 8);
        if (v == ~0ull) return fail(EINVAL);
        for (;;) {
            int r = wait_on(*this, [&] {
                std::lock_guard<std::mutex> l(lock_);
                return count_ <= ~0ull - 1 - v;
            });
            if (r < 0) return fail(-r);
            std::lock_guard<std::mutex> l(lock_);
            // Another writer filled it first: wait again, as Linux's would not overflow.
            if (count_ > ~0ull - 1 - v) continue;
            count_ += v;
            break;
        }
        notify();
        return 8;
    }
    short ready(short events) override {
        std::lock_guard<std::mutex> l(lock_);
        short r = 0;
        if (count_ > 0) r |= POLLIN;
        if (count_ < ~0ull - 1) r |= POLLOUT;
        return static_cast<short>(r & events);
    }

private:
    std::mutex lock_;
    std::uint64_t count_;
    bool semaphore_;
};

// Epolls put inside epolls, one ADD at a time: two at once could each miss the loop the other makes.
std::mutex g_epoll_nesting;

// epoll: its interest list, with EPOLLONESHOT and EPOLLET (an edge-triggered entry is told of what became ready since
// the last look, or of anything ready after a change since it was last told: more data, room again), and a wait in
// progress woken by changes to the list. An entry is the descriptor's number and the object behind it, as Linux keys
// it: a number closed and opened again for another file is another entry.
class Epoll : public Fd {
public:
    struct Interest {
        std::weak_ptr<Fd> fd;
        std::uint32_t events;
        std::uint64_t data;
        bool disabled = false;
        // An edge-triggered entry's state: what was ready at the last look, and the object's count of changes when it
        // was last told.
        short last = 0;
        std::uint64_t told_at = 0;
    };
    int ctl(int op, int fd, const struct epoll_event* ev) {
        std::shared_ptr<Fd> f = fd_get(fd);
        if (!f) return fail(EBADF);
        if (f.get() == this) return fail(EINVAL);
        // An epoll put inside this one: not when this one is inside it already, however deep, or the epolls would nest
        // deeper than Linux allows. ELOOP, as Linux says; a loop would have every look go round it for ever.
        std::unique_lock<std::mutex> nesting;
        if (auto* inner = dynamic_cast<Epoll*>(f.get()); inner && op == EPOLL_CTL_ADD) {
            nesting = std::unique_lock<std::mutex>(g_epoll_nesting);
            if (inner->reaches(this, 1)) return fail(ELOOP);
        }
        {
            std::lock_guard<std::mutex> l(lock_);
            const Key key{fd, f.get()};
            auto it = interests_.find(key);
            // An entry whose object went, and another took its place in memory: gone, as Linux drops it.
            if (it != interests_.end() && it->second.fd.expired()) {
                interests_.erase(it);
                it = interests_.end();
            }
            if (op == EPOLL_CTL_ADD) {
                if (it != interests_.end()) return fail(EEXIST);
                interests_[key] = Interest{f, ev->events, ev->data.u64};
            } else if (op == EPOLL_CTL_MOD) {
                if (it == interests_.end()) return fail(ENOENT);
                // Armed again, and an edge-triggered entry told of what is ready now, as Linux does.
                it->second = Interest{f, ev->events, ev->data.u64};
            } else if (op == EPOLL_CTL_DEL) {
                if (it == interests_.end()) return fail(ENOENT);
                interests_.erase(it);
            } else {
                return fail(EINVAL);
            }
        }
        // A wait in progress looks again, at the list as it is now.
        notify();
        return 0;
    }
    // The entries to tell of now, up to `max`.
    int collect(struct epoll_event* out, int max) {
        std::lock_guard<std::mutex> l(lock_);
        // Descriptors closed since: Linux drops them from the set when their last reference goes.
        for (auto it = interests_.begin(); it != interests_.end();) it = it->second.fd.expired() ? interests_.erase(it) : std::next(it);
        int n = 0;
        // Once round the list from where the last collect stopped: with more ready than `max`, each gets its turn.
        auto it = interests_.lower_bound(next_);
        for (std::size_t looked = 0; looked < interests_.size() && n < max; ++looked, ++it) {
            if (it == interests_.end()) it = interests_.begin();
            std::shared_ptr<Fd> f = it->second.fd.lock();
            // Gone since the sweep above.
            if (!f) continue;
            short r = due(it->second, *f, true);
            if (!r) continue;
            out[n].events = static_cast<std::uint32_t>(r);
            out[n].data.u64 = it->second.data;
            ++n;
            if (it->second.events & EPOLLONESHOT) it->second.disabled = true;
        }
        if (!interests_.empty()) next_ = (it == interests_.end() ? interests_.begin() : it)->first;
        return n;
    }
    // Everything it watches, for a wait to register with.
    std::vector<std::shared_ptr<Fd>> watched() {
        std::lock_guard<std::mutex> l(lock_);
        std::vector<std::shared_ptr<Fd>> out;
        for (auto& [key, in] : interests_)
            if (auto f = in.fd.lock()) out.push_back(f);
        return out;
    }
    // Readable when an entry is due: an epoll inside another's set, or in a poll.
    short ready(short events) override {
        std::lock_guard<std::mutex> l(lock_);
        for (auto& [key, in] : interests_)
            if (auto f = in.fd.lock(); f && due(in, *f, false)) return static_cast<short>(events & POLLIN);
        return 0;
    }
    // Its list's changes and those of everything it watches: for an edge-triggered entry on this epoll in another, an
    // event inside is a new edge, as Linux passes the wake up out.
    std::uint64_t change_count() override {
        std::lock_guard<std::mutex> l(lock_);
        std::uint64_t n = changes();
        for (auto& [key, in] : interests_)
            if (auto f = in.fd.lock()) n += f->change_count();
        return n;
    }
    // Whether `target` is this epoll or inside it, however deep; true as well past the depth of epolls Linux allows
    // (EP_MAX_NESTS: four below the outermost). `depth`: this epoll's own, under the one it would be put in.
    bool reaches(const Epoll* target, int depth) {
        if (this == target || depth > 4) return true;
        for (auto& w : watched())
            if (auto* e = dynamic_cast<Epoll*>(w.get()); e && e->reaches(target, depth + 1)) return true;
        return false;
    }

private:
    using Key = std::pair<int, const Fd*>;
    // What `in` is to be told of now, if anything; with `update`, its edge-triggered state moves on. Under the lock.
    static short due(Interest& in, Fd& f, bool update) {
        if (in.disabled) return 0;
        // A network event since, counted as a change, before the look.
        f.take_event();
        const std::uint64_t changes = f.change_count();
        const short r = f.ready(static_cast<short>((in.events & 0xffff) | POLLHUP | POLLERR));
        if (!(in.events & EPOLLET)) return r;
        const bool edge = (r & ~in.last) || (r && changes != in.told_at);
        if (update) {
            in.last = r;
            if (edge) in.told_at = changes;
        }
        return edge ? r : 0;
    }
    std::mutex lock_;
    std::map<Key, Interest> interests_;
    // Where the next collect starts.
    Key next_{0, nullptr};
};

// What a wait registers with: the objects, each once (Windows waits on a handle only once in a call), and each epoll
// among them with its count of changes from before its list was read.
struct WaitList {
    std::vector<std::shared_ptr<Fd>> fds;
    std::unordered_set<const Fd*> seen;
    std::vector<std::pair<const Epoll*, std::uint64_t>> lists;
};

// `f` into `w`, and for an epoll everything it watches, whose changes are its own (as deep as Linux nests epolls).
void add_watch(WaitList& w, const std::shared_ptr<Fd>& f, int depth = 0) {
    if (!w.seen.insert(f.get()).second) return;
    w.fds.push_back(f);
    if (auto* e = dynamic_cast<Epoll*>(f.get()); e && depth <= 4) {
        // Its count first: an ADD after its list is read shows there, even before the wait registers with it.
        w.lists.emplace_back(e, e->changes());
        for (auto& x : e->watched()) add_watch(w, x, depth + 1);
    }
}

// Waits until `check` finds something ready (the number ready) among the objects `watch` names, or the deadline (0), or
// a signal (-EINTR). The objects are asked for again after every wake, so that a wait on an epoll sees what was added
// to it meanwhile.
template <class Watch, class Check>
int wait_ready(Watch&& watch, long long deadline, Check&& check) {
    HANDLE ev = thread_event();
    for (;;) {
        WaitList w;
        for (auto& f : watch()) add_watch(w, f);
        std::vector<std::shared_ptr<Fd>>& fds = w.fds;
        // Registered, and the network events cleared, before looking: a change after the look sets one of them again.
        for (auto& f : fds) {
            f->add_waiter(ev);
            f->take_event();
        }
        int n = check();
        // An epoll's list changed after it was read and before the wait registered with the epoll: what was added is
        // not registered, and its changes would wake no one. The list is read again at once.
        const bool stale = std::any_of(w.lists.begin(), w.lists.end(), [](const auto& l) { return l.first->changes() != l.second; });
        // Something ready, or the time is up: a wait woken over and over still ends at its deadline.
        const bool late = deadline >= 0 && monotonic_ns() >= deadline;
        if (n != 0 || late || stale) {
            for (auto& f : fds) f->remove_waiter(ev);
            if (n != 0 || late) return n;
            continue;
        }
        // The objects' own handles (a socket's network events), and this thread's event.
        std::vector<HANDLE> handles{ev};
        for (auto& f : fds)
            if (HANDLE h = f->wait_handle()) handles.push_back(h);
        // A socket's event can miss a change; a look every 50 ms catches it.
        long long until = deadline;
        if (handles.size() > 1) {
            long long slice = monotonic_ns() + 50000000LL;
            until = deadline < 0 ? slice : std::min(deadline, slice);
        }
        int r = wait_any(handles.data(), static_cast<int>(handles.size()), until);
        for (auto& f : fds) f->remove_waiter(ev);
        if (r == -EINTR) return r;
    }
}

// A Linux path as a Windows one: forward slashes as they are (Win32 takes them), the devices the layer gives itself.
std::wstring host_path(const char* path) { return wide(path); }

// The layer's own names: /dev and /proc and what is under them, which it answers by name where it can (open_device,
// access, readlink). On Windows nothing of the guest's stands behind any of them, and Windows would read one as the
// current drive's \dev or \proc, another program's folder or none: no call hands one to Windows' file system, and each
// fails there as on a missing file.
bool own_name(const std::string& p) {
    // The folder itself, or a name below it ("/devices" is not one).
    auto in = [&p](const std::string& top) { return p.compare(0, top.size(), top) == 0 && (p.size() == top.size() || p[top.size()] == '/'); };
    return in("/dev") || in("/proc");
}

// Whether a path stays as it is beside a folder descriptor: a Linux absolute one ("/..."), or one made for Windows
// ("C:/...", "\\server\..."), which the player's mapping of the guest's names gives (desktop/guest_paths.h). Any other
// is below the descriptor's folder.
bool absolute_path(const std::string& p) { return !p.empty() && (p[0] == '/' || p[0] == '\\' || (p.size() > 1 && p[1] == ':')); }

// The program's check of the paths no call may change (arm32_set_read_only): none until it sets one.
std::atomic<bool (*)(const char*)> g_read_only{nullptr};

// Whether the program's check refuses a change to `path`: asked with the path as Windows reads it, a relative one after
// the current folder with Linux's separators, as getcwd gives it (the player's names are spelt so too).
bool read_only(const std::string& path) {
    bool (*check)(const char*) = g_read_only.load(std::memory_order_acquire);
    if (!check) return false;
    if (absolute_path(path)) return check(path.c_str());
    wchar_t w[32768];
    const DWORD n = GetCurrentDirectoryW(32768, w);
    std::string full = narrow(w, static_cast<int>(n));
    std::replace(full.begin(), full.end(), '\\', '/');
    return check((full + "/" + path).c_str());
}

// A thread's name: its description, which prctl(PR_SET_NAME) gives it (sys.cpp); "thread" for one without.
std::string thread_description(HANDLE thread) {
    std::string name = thread_name(thread);
    return name.empty() ? std::string("thread") : name;
}

// Linux's stat line for CPU time: the name in parentheses, the state, ten numbers that do not matter here, then the user
// and system time in clock ticks of 1/100 s (Windows counts 100 ns), as the runtime's diagnostics read them.
std::string stat_line(unsigned long id, const std::string& name, const FILETIME& user, const FILETIME& system) {
    auto ticks = [](const FILETIME& t) { return (static_cast<unsigned long long>(t.dwHighDateTime) << 32 | t.dwLowDateTime) / 100000; };
    char buf[256];
    std::snprintf(buf, sizeof buf, "%lu (%s) R 0 0 0 0 0 0 0 0 0 0 %llu %llu 0 0 20 0 1 0 0 0 0\n", id, name.c_str(), ticks(user), ticks(system));
    return buf;
}

// The files of /proc Linux programs read about the process and the machine, made from Windows' own figures: the
// process's memory (statm, status: its working set as what is resident), the computer's (meminfo), and the CPU time
// and names of the process and its threads (stat, task/<id>/stat and task/<id>/comm, the id being Windows' thread id).
std::string proc_text(const std::string& p) {
    if (p == "/proc/self/stat") {
        FILETIME created, ended, system, user;
        if (!GetProcessTimes(GetCurrentProcess(), &created, &ended, &system, &user)) return {};
        return stat_line(GetCurrentProcessId(), "arm32", user, system);
    }
    if (p.rfind("/proc/self/task/", 0) == 0) {
        // The thread by its id, the number after task/.
        const std::string rest = p.substr(16);
        const std::size_t slash = rest.find('/');
        if (slash == std::string::npos || slash == 0 || rest.find_first_not_of("0123456789") != slash) return {};
        const std::string file = rest.substr(slash + 1);
        if (file != "stat" && file != "comm") return {};
        HANDLE thread = OpenThread(THREAD_QUERY_LIMITED_INFORMATION, FALSE, static_cast<DWORD>(std::stoul(rest.substr(0, slash))));
        if (!thread) return {};
        std::string text;
        FILETIME created, ended, system, user;
        if (file == "comm") text = thread_description(thread) + "\n";
        else if (GetThreadTimes(thread, &created, &ended, &system, &user)) text = stat_line(GetThreadId(thread), thread_description(thread), user, system);
        CloseHandle(thread);
        return text;
    }
    PROCESS_MEMORY_COUNTERS_EX pm{};
    pm.cb = sizeof pm;
    GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pm), sizeof pm);
    MEMORYSTATUSEX ms{};
    ms.dwLength = sizeof ms;
    GlobalMemoryStatusEx(&ms);
    char buf[1024];
    if (p == "/proc/self/statm") {
        // Pages: total, resident, shared, text, library, data, dirty.
        std::snprintf(buf, sizeof buf, "%llu %llu 0 0 0 %llu 0\n", static_cast<unsigned long long>(pm.PrivateUsage / 4096),
                      static_cast<unsigned long long>(pm.WorkingSetSize / 4096), static_cast<unsigned long long>(pm.PrivateUsage / 4096));
        return buf;
    }
    if (p == "/proc/self/status") {
        std::snprintf(buf, sizeof buf, "Name:\tarm32\nPid:\t%lu\nVmPeak:\t%llu kB\nVmSize:\t%llu kB\nVmHWM:\t%llu kB\nVmRSS:\t%llu kB\n",
                      static_cast<unsigned long>(GetCurrentProcessId()), static_cast<unsigned long long>(pm.PeakPagefileUsage / 1024),
                      static_cast<unsigned long long>(pm.PrivateUsage / 1024), static_cast<unsigned long long>(pm.PeakWorkingSetSize / 1024),
                      static_cast<unsigned long long>(pm.WorkingSetSize / 1024));
        return buf;
    }
    if (p == "/proc/meminfo") {
        std::snprintf(buf, sizeof buf, "MemTotal:       %llu kB\nMemFree:        %llu kB\nMemAvailable:   %llu kB\nSwapTotal:      %llu kB\nSwapFree:       %llu kB\n",
                      static_cast<unsigned long long>(ms.ullTotalPhys / 1024), static_cast<unsigned long long>(ms.ullAvailPhys / 1024),
                      static_cast<unsigned long long>(ms.ullAvailPhys / 1024),
                      static_cast<unsigned long long>((ms.ullTotalPageFile > ms.ullTotalPhys ? ms.ullTotalPageFile - ms.ullTotalPhys : 0) / 1024),
                      static_cast<unsigned long long>((ms.ullAvailPageFile > ms.ullAvailPhys ? ms.ullAvailPageFile - ms.ullAvailPhys : 0) / 1024));
        return buf;
    }
    return {};
}

int open_device(const std::string& p) {
    if (std::string text = proc_text(p); !text.empty()) {
        // A file of its own with the text, read from its start.
        auto m = std::make_shared<Memfd>();
        m->pwrite(text.data(), text.size(), 0);
        m->path = p;
        m->status_flags = O_RDONLY;
        return fd_add(m, false);
    }
    if (p == "/dev/null") return fd_add(std::make_shared<Device>(Device::kNull), false);
    if (p == "/dev/zero") return fd_add(std::make_shared<Device>(Device::kZero), false);
    if (p == "/dev/urandom" || p == "/dev/random") return fd_add(std::make_shared<Device>(Device::kRandom), false);
    return -2;
}

}  // namespace

}  // namespace arm32::win

using namespace arm32::win;

namespace arm32::posix {

int open(const char* path, int flags, ...) {
    unsigned int mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, unsigned int);
        va_end(ap);
    }
    std::string p = path;
    if (int d = open_device(p); d != -2) {
        if (d >= 0) fd_set_cloexec(d, flags & O_CLOEXEC);
        return d;
    }
    // One of the layer's names it has no answer for: missing, not the current drive's file by that name.
    if (own_name(p)) return fail(ENOENT);
    std::wstring w = host_path(path);
    DWORD attrs = GetFileAttributesW(w.c_str());
    bool is_dir = attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY);
    if ((flags & O_DIRECTORY) && !is_dir) return fail(attrs == INVALID_FILE_ATTRIBUTES ? ENOENT : ENOTDIR);
    const int acc = flags & O_ACCMODE;
    if (is_dir && acc != O_RDONLY) return fail(EISDIR);
    // A write, or a file made, where the program allows no change: refused as a read-only file system refuses it. An
    // existing file opened with O_CREAT to be read makes nothing, and opens, as on Linux.
    const bool writes = acc != O_RDONLY || (flags & O_TRUNC);
    const bool makes = (flags & O_CREAT) && attrs == INVALID_FILE_ATTRIBUTES;
    if ((writes || makes) && read_only(p)) return fail(EROFS);
    DWORD access = acc == O_WRONLY ? GENERIC_WRITE : acc == O_RDWR ? (GENERIC_READ | GENERIC_WRITE) : GENERIC_READ;
    DWORD disposition = OPEN_EXISTING;
    if (flags & O_CREAT) disposition = (flags & O_EXCL) ? CREATE_NEW : (flags & O_TRUNC) ? CREATE_ALWAYS : OPEN_ALWAYS;
    else if (flags & O_TRUNC) disposition = TRUNCATE_EXISTING;
    // Deletable and renamable while open, as on Linux; directories need backup semantics to be opened at all.
    DWORD attributes = (is_dir ? FILE_FLAG_BACKUP_SEMANTICS : FILE_ATTRIBUTE_NORMAL) | ((flags & O_CREAT) && !(mode & 0200) ? FILE_ATTRIBUTE_READONLY : 0);
    HANDLE h = CreateFileW(w.c_str(), access, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, disposition, attributes, nullptr);
    if (h == INVALID_HANDLE_VALUE) return fail_win32();
    std::shared_ptr<Fd> f = is_dir ? std::shared_ptr<Fd>(std::make_shared<Dir>(h, w)) : std::shared_ptr<Fd>(std::make_shared<File>(h));
    f->path = p;
    f->status_flags = flags & (O_APPEND | O_NONBLOCK | O_ACCMODE);
    return fd_add(std::move(f), flags & O_CLOEXEC);
}

int openat(int dirfd, const char* path, int flags, ...) {
    unsigned int mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, unsigned int);
        va_end(ap);
    }
    // A relative path under a directory descriptor: that directory's path in front.
    std::string p = path;
    if (!absolute_path(p) && dirfd != AT_FDCWD) {
        std::shared_ptr<Fd> d = fd_get(dirfd);
        if (!d) return fail(EBADF);
        p = d->path + "/" + p;
    }
    return open(p.c_str(), flags, mode);
}

int close(int fd) { return fd_close(fd); }

ssize_t read(int fd, void* buf, std::size_t n) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->read(buf, n) : fail(EBADF);
}

ssize_t write(int fd, const void* buf, std::size_t n) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->write(buf, n) : fail(EBADF);
}

ssize_t pread(int fd, void* buf, std::size_t n, long long offset) {
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    // No place before the start, as Linux says (and Windows would read an offset of all ones as the end).
    return offset < 0 ? fail(EINVAL) : f->pread(buf, n, offset);
}

ssize_t pread64(int fd, void* buf, std::size_t n, long long offset) { return pread(fd, buf, n, offset); }

ssize_t pwrite(int fd, const void* buf, std::size_t n, long long offset) {
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    // As pread: an offset of all ones would write at the end.
    return offset < 0 ? fail(EINVAL) : f->pwrite(buf, n, offset);
}

ssize_t readv(int fd, const struct iovec* iov, int n) {
    // Linux's limit on the buffers.
    if (n < 0 || n > 1024) return fail(EINVAL);
    std::size_t total = 0;
    for (int i = 0; i < n; ++i) total += iov[i].iov_len;
    // Nothing to read: 0 at once, whatever the descriptor, as Linux's readv returns before it reads.
    if (total == 0) return fd_get(fd) ? 0 : fail(EBADF);
    if (n == 1) return read(fd, iov[0].iov_base, iov[0].iov_len);
    // One read of the whole length, spread over the buffers after: a read for each would wait on a pipe or a socket
    // for more once the first is full, where Linux gives what is there.
    std::vector<std::uint8_t> all(total);
    ssize_t r = read(fd, all.data(), total);
    if (r <= 0) return r;
    std::size_t at = 0;
    for (int i = 0; i < n && at < static_cast<std::size_t>(r); ++i) {
        std::size_t k = std::min(iov[i].iov_len, static_cast<std::size_t>(r) - at);
        std::memcpy(iov[i].iov_base, all.data() + at, k);
        at += k;
    }
    return r;
}

ssize_t writev(int fd, const struct iovec* iov, int n) {
    // Linux's limit on the buffers, as readv.
    if (n < 0 || n > 1024) return fail(EINVAL);
    // One write of everything: a datagram (the log's) must not be cut into parts.
    std::vector<std::uint8_t> all;
    for (int i = 0; i < n; ++i) {
        const auto* p = static_cast<const std::uint8_t*>(iov[i].iov_base);
        all.insert(all.end(), p, p + iov[i].iov_len);
    }
    return write(fd, all.data(), all.size());
}

long long lseek(int fd, long long offset, int whence) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->seek(offset, whence) : fail(EBADF);
}

int fstat(int fd, struct stat* st) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->stat(st) : fail(EBADF);
}

int lstat(const char* path, struct stat* st) { return ::stat(path, st); }

int fstatat(int dirfd, const char* path, struct stat* st, int flags) {
    if ((flags & AT_EMPTY_PATH) && (!path || !*path)) return fstat(dirfd, st);
    int fd = openat(dirfd, path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    int r = fstat(fd, st);
    close(fd);
    return r;
}

int fstatfs(int, struct statfs* st) {
    std::memset(st, 0, sizeof *st);
    // An ext4-like file system of 4 KB blocks.
    st->f_type = 0xEF53;
    st->f_bsize = st->f_frsize = 4096;
    st->f_blocks = st->f_bfree = st->f_bavail = 1u << 24;
    st->f_files = st->f_ffree = 1u << 20;
    st->f_namelen = 255;
    return 0;
}

int fcntl(int fd, int cmd, ...) {
    va_list ap;
    va_start(ap, cmd);
    std::intptr_t arg = va_arg(ap, std::intptr_t);
    va_end(ap);
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    switch (cmd) {
    case F_GETFD:
        return fd_cloexec(fd) ? FD_CLOEXEC : 0;
    case F_SETFD:
        fd_set_cloexec(fd, arg & FD_CLOEXEC);
        return 0;
    case F_GETFL:
        return f->status_flags.load();
    case F_SETFL:
        f->status_flags = (f->status_flags.load() & O_ACCMODE) | (static_cast<int>(arg) & (O_APPEND | O_NONBLOCK));
        return 0;
    case F_DUPFD:
    case F_DUPFD_CLOEXEC:
        return fd_add(f, cmd == F_DUPFD_CLOEXEC, static_cast<int>(arg));
    case F_GETLK:
    case 36: {  // F_OFD_GETLK
        // No other process holds a lock here.
        auto* lk = reinterpret_cast<struct flock*>(arg);
        lk->l_type = F_UNLCK;
        return 0;
    }
    case F_SETLK:
    case F_SETLKW:
    case 37:  // F_OFD_SETLK
    case 38:  // F_OFD_SETLKW
        return 0;
    case F_SETOWN:
        f->owner = static_cast<int>(arg);
        return 0;
    case F_GETOWN:
        return f->owner;
    case 15: {  // F_SETOWN_EX: struct f_owner_ex { int type; pid_t pid; }
        f->owner = reinterpret_cast<const int*>(arg)[1];
        return 0;
    }
    case 16: {  // F_GETOWN_EX
        auto* owner = reinterpret_cast<int*>(arg);
        owner[0] = 1;  // F_OWNER_PID
        owner[1] = f->owner;
        return 0;
    }
    case 17: {  // F_GETOWNER_UIDS: the real and effective owners, the process's own
        auto* uids = reinterpret_cast<unsigned int*>(arg);
        uids[0] = uids[1] = getuid();
        return 0;
    }
    case F_SETSIG:
        f->signal = static_cast<int>(arg);
        return 0;
    case F_GETSIG:
        return f->signal;
    case F_SETLEASE:
    case F_NOTIFY:
        return 0;
    case F_GETLEASE:
        return F_UNLCK;
    case 1031:  // F_SETPIPE_SZ: what a pipe holds, a page at least
    case 1032:  // F_GETPIPE_SZ
        if (!dynamic_cast<PipeEnd*>(f.get())) return fail(EBADF);
        return cmd == 1031 ? std::max(4096, static_cast<int>(arg)) : static_cast<int>(PipeBuffer::kCapacity);
    case 1033:  // F_ADD_SEALS
    case 1034:  // F_GET_SEALS: only a memfd can be sealed, and none is
        if (!dynamic_cast<Memfd*>(f.get())) return fail(EINVAL);
        return 0;
    case 1035:  // F_GET_RW_HINT
    case 1037:  // F_GET_FILE_RW_HINT
        *reinterpret_cast<std::uint64_t*>(arg) = 0;
        return 0;
    case 1036:  // F_SET_RW_HINT
    case 1038:  // F_SET_FILE_RW_HINT
        return 0;
    default:
        return fail(EINVAL);
    }
}

int ioctl(int fd, unsigned long request, ...) {
    va_list ap;
    va_start(ap, request);
    void* arg = va_arg(ap, void*);
    va_end(ap);
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    if (request == FIONBIO) {
        int on = arg ? *static_cast<int*>(arg) : 0;
        f->status_flags = on ? (f->status_flags.load() | O_NONBLOCK) : (f->status_flags.load() & ~O_NONBLOCK);
        return 0;
    }
    if (request == FIONREAD) {
        // What a read would get now: a pipe's or a socket's bytes waiting, a file's rest.
        long n = f->bytes_ready();
        *static_cast<int*>(arg) = static_cast<int>(std::min<long>(n, INT_MAX));
        return 0;
    }
    // No terminals.
    return fail(ENOTTY);
}

int dup(int fd) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? fd_add(f, false) : fail(EBADF);
}

int dup2(int fd, int to) {
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    if (fd == to) return to;
    return fd_put(to, f, false);
}

int dup3(int fd, int to, int flags) {
    if (fd == to) return fail(EINVAL);
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    return fd_put(to, f, flags & O_CLOEXEC);
}

int pipe2(int fds[2], int flags) {
    auto b = std::make_shared<PipeBuffer>();
    auto r = std::make_shared<PipeEnd>(b, true), w = std::make_shared<PipeEnd>(b, false);
    r->status_flags = O_RDONLY | (flags & O_NONBLOCK);
    w->status_flags = O_WRONLY | (flags & O_NONBLOCK);
    fds[0] = fd_add(r, flags & O_CLOEXEC);
    if (fds[0] < 0) return -1;
    fds[1] = fd_add(w, flags & O_CLOEXEC);
    if (fds[1] < 0) {
        close(fds[0]);
        return -1;
    }
    return 0;
}

int ftruncate(int fd, long long size) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->truncate(size) : fail(EBADF);
}

int ftruncate64(int fd, long long size) { return ftruncate(fd, size); }

int truncate(const char* path, long long size) {
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    int r = ftruncate(fd, size);
    close(fd);
    return r;
}

int fsync(int fd) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? f->sync() : fail(EBADF);
}

int fdatasync(int fd) { return fsync(fd); }

int flock(int fd, int) { return fd_get(fd) ? 0 : fail(EBADF); }

int access(const char* path, int mode) {
    std::string p = path;
    if (p == "/dev/null" || p == "/dev/zero" || p == "/dev/urandom" || p == "/dev/random" || !proc_text(p).empty()) return 0;
    // The layer's other names: missing (own_name).
    if (own_name(p)) return fail(ENOENT);
    DWORD attrs = GetFileAttributesW(host_path(path).c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES) return fail_win32();
    if ((mode & W_OK) && (attrs & FILE_ATTRIBUTE_READONLY) && !(attrs & FILE_ATTRIBUTE_DIRECTORY)) return fail(EACCES);
    return 0;
}

int faccessat(int dirfd, const char* path, int mode, int) {
    std::string p = path;
    if (!p.empty() && !absolute_path(p) && dirfd != AT_FDCWD) {
        std::shared_ptr<Fd> d = fd_get(dirfd);
        if (!d) return fail(EBADF);
        p = d->path + "/" + p;
    }
    return access(p.c_str(), mode);
}

int unlink(const char* path) {
    // Not a file of Windows' by one of the layer's names (own_name).
    if (own_name(path)) return fail(ENOENT);
    // Nothing goes where the program allows no change (arm32_set_read_only).
    if (read_only(path)) return fail(EROFS);
    std::wstring w = host_path(path);
    // Read-only files go too, as Linux deletes them by the folder's permission.
    DWORD attrs = GetFileAttributesW(w.c_str());
    if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY)) return fail(EISDIR);
    if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_READONLY)) SetFileAttributesW(w.c_str(), attrs & ~FILE_ATTRIBUTE_READONLY);
    return DeleteFileW(w.c_str()) ? 0 : fail_win32();
}

int unlinkat(int dirfd, const char* path, int flags) {
    std::string p = path;
    if (!p.empty() && !absolute_path(p) && dirfd != AT_FDCWD) {
        std::shared_ptr<Fd> d = fd_get(dirfd);
        if (!d) return fail(EBADF);
        p = d->path + "/" + p;
    }
    return (flags & AT_REMOVEDIR) ? rmdir(p.c_str()) : unlink(p.c_str());
}

int mkdir(const char* path, unsigned int) {
    // No folder of Windows' by one of the layer's names (own_name).
    if (own_name(path)) return fail(ENOENT);
    // No new folder where the program allows no change; one that is there already is EEXIST, as on Linux, so that a walk
    // that makes each folder on its way goes on through them.
    if (read_only(path) && GetFileAttributesW(host_path(path).c_str()) == INVALID_FILE_ATTRIBUTES) return fail(EROFS);
    if (CreateDirectoryW(host_path(path).c_str(), nullptr)) return 0;
    return fail_win32();
}

int mkdirat(int dirfd, const char* path, unsigned int mode) {
    std::string p = path;
    if (!p.empty() && !absolute_path(p) && dirfd != AT_FDCWD) {
        std::shared_ptr<Fd> d = fd_get(dirfd);
        if (!d) return fail(EBADF);
        p = d->path + "/" + p;
    }
    return mkdir(p.c_str(), mode);
}

int rmdir(const char* path) {
    // Not a folder of Windows' by one of the layer's names (own_name).
    if (own_name(path)) return fail(ENOENT);
    // Nothing goes where the program allows no change (arm32_set_read_only).
    if (read_only(path)) return fail(EROFS);
    return RemoveDirectoryW(host_path(path).c_str()) ? 0 : fail_win32();
}

int renameat(int fromfd, const char* from, int tofd, const char* to) {
    auto full = [](int dirfd, const char* path) {
        std::string p = path;
        if (!p.empty() && !absolute_path(p) && dirfd != AT_FDCWD)
            if (std::shared_ptr<Fd> d = fd_get(dirfd)) p = d->path + "/" + p;
        return p;
    };
    return arm32_rename(full(fromfd, from).c_str(), full(tofd, to).c_str());
}

ssize_t readlink(const char* path, char* buf, std::size_t n) {
    // /proc/self/fd/N: the path the descriptor was opened by. Nothing else is a link here.
    std::string p = path;
    const std::string prefix = "/proc/self/fd/";
    if (p.rfind(prefix, 0) == 0) {
        std::shared_ptr<Fd> f = fd_get(std::atoi(p.c_str() + prefix.size()));
        if (!f) return fail(ENOENT);
        std::size_t k = std::min(n, f->path.size());
        std::memcpy(buf, f->path.data(), k);
        return static_cast<ssize_t>(k);
    }
    return fail(EINVAL);
}

ssize_t readlinkat(int, const char* path, char* buf, std::size_t n) { return readlink(path, buf, n); }

int chdir(const char* path) {
    // Not into a folder of Windows' by one of the layer's names (own_name).
    if (own_name(path)) return fail(ENOENT);
    return SetCurrentDirectoryW(host_path(path).c_str()) ? 0 : fail_win32();
}

int fchdir(int fd) {
    std::shared_ptr<Fd> f = fd_get(fd);
    return f ? chdir(f->path.c_str()) : fail(EBADF);
}

char* getcwd(char* buf, std::size_t n) {
    if (!buf) {
        errno = EFAULT;
        return nullptr;
    }
    wchar_t w[32768];
    DWORD len = GetCurrentDirectoryW(32768, w);
    std::string s = narrow(w, static_cast<int>(len));
    // Linux's separators.
    std::replace(s.begin(), s.end(), '\\', '/');
    if (s.size() + 1 > n) {
        errno = ERANGE;
        return nullptr;
    }
    std::memcpy(buf, s.c_str(), s.size() + 1);
    return buf;
}

unsigned int umask(unsigned int mask) {
    static std::atomic<unsigned int> current{022};
    return current.exchange(mask & 0777);
}

int utimensat(int dirfd, const char* path, const struct timespec times[2], int) {
    int fd = path ? openat(dirfd, path, O_RDWR | O_CLOEXEC) : dirfd;
    if (fd < 0) return -1;
    std::shared_ptr<Fd> f = fd_get(fd);
    auto* file = dynamic_cast<File*>(f.get());
    int r = 0;
    if (file) {
        FILETIME now;
        GetSystemTimeAsFileTime(&now);
        auto ft = [&](const struct timespec& t) {
            if (t.tv_nsec == UTIME_NOW) return now;
            long long v = static_cast<long long>(t.tv_sec) * 10000000LL + t.tv_nsec / 100 + 116444736000000000LL;
            FILETIME out;
            out.dwLowDateTime = static_cast<DWORD>(v);
            out.dwHighDateTime = static_cast<DWORD>(v >> 32);
            return out;
        };
        FILETIME a = times ? ft(times[0]) : now, m = times ? ft(times[1]) : now;
        bool skip_a = times && times[0].tv_nsec == UTIME_OMIT, skip_m = times && times[1].tv_nsec == UTIME_OMIT;
        if (!SetFileTime(file->handle(), nullptr, skip_a ? nullptr : &a, skip_m ? nullptr : &m)) r = fail_win32();
    }
    if (path) close(fd);
    return r;
}

int chmod(const char* path, unsigned int mode) {
    // Not a file of Windows' by one of the layer's names (own_name).
    if (own_name(path)) return fail(ENOENT);
    // No change of mode where the program allows no change (arm32_set_read_only).
    if (read_only(path)) return fail(EROFS);
    std::wstring w = host_path(path);
    DWORD attrs = GetFileAttributesW(w.c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES) return fail_win32();
    // Only "writable or not" is a file's on Windows.
    attrs = (mode & 0200) ? (attrs & ~FILE_ATTRIBUTE_READONLY) : (attrs | FILE_ATTRIBUTE_READONLY);
    return SetFileAttributesW(w.c_str(), attrs) ? 0 : fail_win32();
}

int fchmod(int fd, unsigned int mode) {
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    return f->path.empty() ? 0 : chmod(f->path.c_str(), mode);
}

int fchmodat(int dirfd, const char* path, unsigned int mode, int) {
    std::string p = path;
    if (!p.empty() && !absolute_path(p) && dirfd != AT_FDCWD)
        if (std::shared_ptr<Fd> d = fd_get(dirfd)) p = d->path + "/" + p;
    return chmod(p.c_str(), mode);
}

int eventfd(unsigned int initial, int flags) {
    auto e = std::make_shared<EventFd>(initial, flags & EFD_SEMAPHORE);
    e->status_flags = O_RDWR | ((flags & EFD_NONBLOCK) ? O_NONBLOCK : 0);
    return fd_add(e, flags & EFD_CLOEXEC);
}

int memfd_create(const char* name, unsigned int flags) {
    auto m = std::make_shared<Memfd>();
    m->path = std::string("/memfd:") + name;
    m->status_flags = O_RDWR;
    return fd_add(m, flags & 1 /* MFD_CLOEXEC */);
}

long getdents64(int fd, void* buf, std::size_t n) {
    std::shared_ptr<Fd> f = fd_get(fd);
    if (!f) return fail(EBADF);
    auto* d = dynamic_cast<Dir*>(f.get());
    if (!d) return fail(ENOTDIR);
    return d->entries(buf, n);
}

// ---------------------------------------------------------------------------------------------------------------------
// Waits on descriptors.

int ppoll(struct pollfd* fds, nfds_t n, const struct timespec* timeout, const void*) {
    std::vector<std::shared_ptr<Fd>> objects;
    std::vector<std::shared_ptr<Fd>> by_index(n);
    for (nfds_t i = 0; i < n; ++i) {
        by_index[i] = fds[i].fd >= 0 ? fd_get(fds[i].fd) : nullptr;
        if (by_index[i]) objects.push_back(by_index[i]);
    }
    auto check = [&] {
        int ready = 0;
        for (nfds_t i = 0; i < n; ++i) {
            fds[i].revents = 0;
            if (fds[i].fd < 0) continue;
            if (!by_index[i]) {
                fds[i].revents = POLLNVAL;
            } else {
                fds[i].revents = by_index[i]->ready(static_cast<short>(fds[i].events | POLLHUP | POLLERR));
            }
            if (fds[i].revents) ++ready;
        }
        return ready;
    };
    long long deadline = -1;
    if (timeout) deadline = monotonic_ns() + static_cast<long long>(timeout->tv_sec) * 1000000000LL + timeout->tv_nsec;
    if (timeout && timeout->tv_sec == 0 && timeout->tv_nsec == 0) return check();
    int r = wait_ready([&]() -> const std::vector<std::shared_ptr<Fd>>& { return objects; }, deadline, check);
    return r < 0 ? fail(-r) : r;
}

int poll(struct pollfd* fds, nfds_t n, int timeout_ms) {
    struct timespec ts {};
    ts.tv_sec = timeout_ms / 1000;
    ts.tv_nsec = (timeout_ms % 1000) * 1000000L;
    return ppoll(fds, n, timeout_ms < 0 ? nullptr : &ts, nullptr);
}

int select(int n, fd_set* r, fd_set* w, fd_set* e, struct timeval* timeout) {
    std::vector<struct pollfd> p;
    for (int fd = 0; fd < n; ++fd) {
        short ev = 0;
        if (r && FD_ISSET(fd, r)) ev |= POLLIN;
        if (w && FD_ISSET(fd, w)) ev |= POLLOUT;
        if (e && FD_ISSET(fd, e)) ev |= POLLPRI;
        if (ev) p.push_back(pollfd{fd, ev, 0});
    }
    struct timespec ts {};
    if (timeout) {
        ts.tv_sec = timeout->tv_sec;
        ts.tv_nsec = timeout->tv_usec * 1000L;
    }
    int k = ppoll(p.data(), p.size(), timeout ? &ts : nullptr, nullptr);
    if (k < 0) return k;
    if (r) FD_ZERO(r);
    if (w) FD_ZERO(w);
    if (e) FD_ZERO(e);
    int count = 0;
    for (const struct pollfd& q : p) {
        if (r && (q.revents & (POLLIN | POLLHUP | POLLERR))) FD_SET(q.fd, r), ++count;
        if (w && (q.revents & (POLLOUT | POLLERR))) FD_SET(q.fd, w), ++count;
        if (e && (q.revents & POLLPRI)) FD_SET(q.fd, e), ++count;
        if (q.revents & POLLNVAL) return fail(EBADF);
    }
    return count;
}

int epoll_create1(int flags) {
    auto e = std::make_shared<Epoll>();
    e->status_flags = O_RDWR;
    return fd_add(e, flags & EPOLL_CLOEXEC);
}

int epoll_create(int size) { return size <= 0 ? fail(EINVAL) : epoll_create1(0); }

int epoll_ctl(int epfd, int op, int fd, struct epoll_event* event) {
    std::shared_ptr<Fd> f = fd_get(epfd);
    auto* e = dynamic_cast<Epoll*>(f.get());
    if (!e) return fail(f ? EINVAL : EBADF);
    if (op != EPOLL_CTL_DEL && !event) return fail(EFAULT);
    return e->ctl(op, fd, event);
}

int epoll_wait(int epfd, struct epoll_event* events, int max, int timeout_ms) {
    std::shared_ptr<Fd> f = fd_get(epfd);
    auto* e = dynamic_cast<Epoll*>(f.get());
    if (!e) return fail(f ? EINVAL : EBADF);
    if (max <= 0) return fail(EINVAL);
    auto check = [&] { return e->collect(events, max); };
    if (timeout_ms == 0) return check();
    long long deadline = timeout_ms < 0 ? -1 : monotonic_ns() + static_cast<long long>(timeout_ms) * 1000000LL;
    // The epoll itself, which its list's changes wake, and what it watches as it is at each look.
    int r = wait_ready([&] { return std::vector<std::shared_ptr<Fd>>{f}; }, deadline, check);
    return r < 0 ? fail(-r) : r;
}

}  // namespace arm32::posix

int stat(const char* path, struct stat* st) {
    int fd = arm32::posix::open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    int r = arm32::posix::fstat(fd, st);
    arm32::posix::close(fd);
    return r;
}

int statfs(const char*, struct statfs* st) { return arm32::posix::fstatfs(-1, st); }

int arm32_rename(const char* from, const char* to) {
    // Neither side a file of Windows' by one of the layer's names (own_name).
    if (own_name(from) || own_name(to)) return fail(ENOENT);
    // Nothing moved out of or into where the program allows no change (arm32_set_read_only).
    if (read_only(from) || read_only(to)) return fail(EROFS);
    std::wstring f = wide(from), t = wide(to);
    // Replaces what is there, as Linux's rename does.
    if (MoveFileExW(f.c_str(), t.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_COPY_ALLOWED)) return 0;
    return fail_win32();
}

void arm32_set_read_only(bool (*check)(const char* path)) { g_read_only.store(check, std::memory_order_release); }
