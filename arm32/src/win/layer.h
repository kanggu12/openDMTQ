// What the files of the Windows layer share (src/win): the descriptor table and the objects behind descriptors, the waits
// a guest signal can cut short, and Windows' errors as Linux's. Linux's names come from arm32_linux.h, which every file
// of the runtime has first; Windows' own from windows.h, which only the layer includes.
#pragma once

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace arm32::win {

// A Win32 error as Linux's errno.
int errno_of(DWORD error);
// Sets errno to Linux's `e` and returns -1, as a failing call does.
inline int fail(int e) {
    errno = e;
    return -1;
}
// The same for the last Win32 error.
inline int fail_win32() { return fail(errno_of(GetLastError())); }

// UTF-8 as UTF-16, and back.
std::wstring wide(const std::string& s);
std::string narrow(const wchar_t* s, int n = -1);

// Something waits on objects (poll, epoll_wait, a blocking read): it gives them its event, which each sets when its
// state changes, and waits on that.
class Waitable {
public:
    void add_waiter(HANDLE event);
    void remove_waiter(HANDLE event);
    // The state changed: everyone waiting looks again.
    void notify();
    // How often its state changed, for epoll's edge-triggered entries: a change while it stays ready is a new edge.
    std::uint64_t changes() const { return changes_.load(); }

protected:
    // Counted by notify, and by the kinds whose changes Windows signals instead (a socket's network events).
    std::atomic<std::uint64_t> changes_{0};

private:
    std::mutex lock_;
    std::vector<HANDLE> waiters_;
};

// What a descriptor stands for. Each kind answers the calls that make sense for it; the rest fail as Linux fails them.
class Fd : public Waitable {
public:
    virtual ~Fd() = default;
    virtual ssize_t read(void* buf, std::size_t n);
    virtual ssize_t write(const void* buf, std::size_t n);
    virtual ssize_t pread(void* buf, std::size_t n, long long offset);
    virtual ssize_t pwrite(const void* buf, std::size_t n, long long offset);
    virtual long long seek(long long offset, int whence);
    virtual int stat(struct stat* st);
    virtual int truncate(long long size);
    virtual int sync();
    // poll's events that hold now (POLLIN, POLLOUT, POLLHUP, ...), of those asked for.
    virtual short ready(short events);
    // A Win32 handle to wait on as well, for what the layer does not see change itself (a socket's network events).
    virtual HANDLE wait_handle() { return nullptr; }
    // That handle, cleared before a look so that a change after the look sets it again, and counted as a change if it
    // was set.
    virtual void take_event() {}
    // The bytes a read would get now, for FIONREAD.
    virtual long bytes_ready() { return 0; }
    // Its count of changes as an edge-triggered epoll entry on it sees them: Waitable's own, and for an epoll those of
    // everything it watches as well, whose new events are its own.
    virtual std::uint64_t change_count() { return changes(); }
    // The path it was opened by, for /proc/self/fd/N.
    std::string path;
    // O_NONBLOCK and O_APPEND, as fcntl reads and sets them, and the access mode.
    std::atomic<int> status_flags{0};
    // fcntl's owner for signals (F_SETOWN) and the signal it would send (F_SETSIG): kept, and never sent here.
    std::atomic<int> owner{0}, signal{0};
};

// The descriptor table: numbers from 0, the lowest free one first, each with its close-on-exec flag.
int fd_add(std::shared_ptr<Fd> f, bool cloexec, int at_least = 0);
std::shared_ptr<Fd> fd_get(int fd);
// Puts `f` at `fd`, closing what was there (dup2).
int fd_put(int fd, std::shared_ptr<Fd> f, bool cloexec);
int fd_close(int fd);
bool fd_cloexec(int fd);
void fd_set_cloexec(int fd, bool on);

// Waits: the handles, this thread's interrupt (when it waits for a guest), until `deadline_ns` on the monotonic clock
// (-1 for ever). 0 when one of the handles is set, -EINTR when the interrupt is, -ETIMEDOUT at the deadline.
int wait_any(const HANDLE* handles, int n, long long deadline_ns);
// This thread's own event, which objects set when it waits on them.
HANDLE thread_event();
// The monotonic clock, in nanoseconds.
long long monotonic_ns();
// Whether this thread's waits are for a guest's system call, which a guest signal cuts short.
extern thread_local bool t_interruptible;

// A thread's name, as Windows keeps it from Windows 10 1607 on (a debugger's, and /proc's comm here): looked up when
// first used, so that an older Windows still starts the program, its threads then without names ("" when it has none).
void set_thread_name(HANDLE thread, const std::wstring& name);
std::string thread_name(HANDLE thread);

}  // namespace arm32::win
