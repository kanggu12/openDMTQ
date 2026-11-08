#!/usr/bin/env python3
# Writes the numbers of Linux's x86-64 interface that the runtime's core names (open flags, mmap flags, futex and epoll
# operations, socket options, errno values, system call numbers and the rest) into a header, for hosts whose own headers
# have other numbers or none: on Windows the runtime's layer below the core (arm32/src/win) gives Linux's calls with
# Linux's numbers. The numbers come from the headers of a Linux x86-64 system, read by its own C compiler, so none is
# copied by hand.
#
#   python3 arm32/tools/gen_linux_abi.py <out header>     (on Linux x86-64, with a C compiler and the kernel's headers)
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The sources built on that layer: every capitalized name in them is a candidate; the compiler says which Linux defines.
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIRS = ["src", "src/win", "desktop", "jvm"]
# Names the core does not spell out but the layer itself needs.
EXTRA = ["O_ACCMODE", "S_IFMT", "S_IFDIR", "S_IFREG", "S_IFLNK", "S_IFIFO", "S_IFSOCK", "S_IFCHR", "S_IFBLK", "EPOLLIN", "EPOLLOUT", "EPOLLERR",
         "EPOLLHUP", "EPOLLRDHUP", "EPOLLET", "EPOLLONESHOT", "EPOLL_CTL_ADD", "EPOLL_CTL_DEL", "EPOLL_CTL_MOD", "POLLIN", "POLLOUT", "POLLERR",
         "POLLHUP", "POLLNVAL", "POLLPRI", "POLLRDNORM", "POLLWRNORM", "EFD_NONBLOCK", "EFD_CLOEXEC", "EFD_SEMAPHORE", "SOCK_NONBLOCK",
         "SOCK_CLOEXEC", "MSG_NOSIGNAL", "MSG_DONTWAIT", "MSG_PEEK", "MSG_WAITALL", "MSG_TRUNC", "MSG_CTRUNC", "TCP_NODELAY", "IPPROTO_TCP",
         "IPPROTO_UDP", "IPPROTO_IP", "IPPROTO_IPV6", "SO_ERROR", "SO_REUSEADDR", "SO_KEEPALIVE", "SO_RCVBUF", "SO_SNDBUF", "SO_RCVTIMEO",
         "SO_SNDTIMEO", "SO_LINGER", "SO_TYPE", "SO_BROADCAST", "SO_PEERCRED", "SO_DOMAIN", "SO_PROTOCOL", "SOL_SOCKET", "SHUT_RD", "SHUT_WR",
         "SHUT_RDWR", "AF_UNSPEC", "AF_UNIX", "AF_INET", "AF_INET6", "AF_NETLINK", "SOCK_STREAM", "SOCK_DGRAM", "SOCK_SEQPACKET", "SOCK_RAW",
         "FIONREAD", "FIONBIO", "TIOCGWINSZ", "TCGETS", "CLOCK_REALTIME", "CLOCK_MONOTONIC", "CLOCK_MONOTONIC_RAW", "CLOCK_BOOTTIME",
         "CLOCK_PROCESS_CPUTIME_ID", "CLOCK_THREAD_CPUTIME_ID", "CLOCK_REALTIME_COARSE", "CLOCK_MONOTONIC_COARSE", "TIMER_ABSTIME", "F_OK",
         "R_OK", "W_OK", "X_OK", "SEEK_SET", "SEEK_CUR", "SEEK_END", "LOCK_SH", "LOCK_EX", "LOCK_NB", "LOCK_UN", "DT_UNKNOWN", "DT_REG",
         "DT_DIR", "DT_LNK", "DT_FIFO", "DT_SOCK", "DT_CHR", "DT_BLK", "AT_FDCWD", "AT_SYMLINK_NOFOLLOW", "AT_REMOVEDIR", "AT_EMPTY_PATH",
         "AT_EACCESS", "UTIME_NOW", "UTIME_OMIT", "WNOHANG", "SIG_BLOCK", "SIG_UNBLOCK", "SIG_SETMASK", "FUTEX_WAIT", "FUTEX_WAKE",
         "FUTEX_WAIT_BITSET", "FUTEX_WAKE_BITSET", "FUTEX_REQUEUE", "FUTEX_CMP_REQUEUE", "FUTEX_WAKE_OP", "FUTEX_CMD_MASK",
         "FUTEX_CLOCK_REALTIME", "FUTEX_PRIVATE_FLAG", "RLIMIT_NOFILE", "RLIMIT_STACK", "SIGKILL", "EPOLL_CLOEXEC", "IPV6_V6ONLY",
         "MSG_OOB", "SO_REUSEPORT", "SO_RCVLOWAT", "SO_SNDLOWAT", "SO_ACCEPTCONN", "AI_PASSIVE", "AI_CANONNAME", "AI_NUMERICHOST",
         "AI_NUMERICSERV", "AI_ADDRCONFIG", "AI_V4MAPPED", "AI_ALL", "EAI_BADFLAGS", "EAI_NONAME", "EAI_AGAIN", "EAI_FAIL", "EAI_FAMILY",
         "EAI_SOCKTYPE", "EAI_SERVICE", "EAI_MEMORY", "EAI_SYSTEM", "EAI_OVERFLOW", "INADDR_ANY", "INADDR_LOOPBACK", "MFD_CLOEXEC"]
HEADERS = ["errno.h", "limits.h", "fcntl.h", "dirent.h", "poll.h", "sched.h", "signal.h", "time.h", "unistd.h", "linux/futex.h", "sys/epoll.h", "sys/file.h",
           "sys/eventfd.h", "sys/ioctl.h", "sys/mman.h", "sys/prctl.h", "sys/resource.h", "sys/socket.h", "netinet/in.h", "netinet/tcp.h",
           "sys/un.h", "sys/stat.h", "sys/statfs.h", "sys/syscall.h", "sys/sysinfo.h", "sys/time.h", "sys/times.h", "sys/uio.h",
           "sys/utsname.h", "sys/wait.h", "sys/inotify.h", "termios.h", "elf.h", "netdb.h", "netinet/in.h", "arpa/inet.h",
           "sys/sysmacros.h", "dirent.h", "dlfcn.h"]
# Every errno value, which the layer sets in place of Windows' own.
ERRNO = ["EPERM", "ENOENT", "ESRCH", "EINTR", "EIO", "ENXIO", "E2BIG", "ENOEXEC", "EBADF", "ECHILD", "EAGAIN", "ENOMEM", "EACCES", "EFAULT",
         "ENOTBLK", "EBUSY", "EEXIST", "EXDEV", "ENODEV", "ENOTDIR", "EISDIR", "EINVAL", "ENFILE", "EMFILE", "ENOTTY", "ETXTBSY", "EFBIG",
         "ENOSPC", "ESPIPE", "EROFS", "EMLINK", "EPIPE", "EDOM", "ERANGE", "EDEADLK", "ENAMETOOLONG", "ENOLCK", "ENOSYS", "ENOTEMPTY",
         "ELOOP", "EWOULDBLOCK", "ENOMSG", "EIDRM", "ENOSTR", "ENODATA", "ETIME", "ENOSR", "ENOLINK", "EPROTO", "EBADMSG", "EOVERFLOW",
         "EILSEQ", "ENOTSOCK", "EDESTADDRREQ", "EMSGSIZE", "EPROTOTYPE", "ENOPROTOOPT", "EPROTONOSUPPORT", "ESOCKTNOSUPPORT", "EOPNOTSUPP",
         "ENOTSUP", "EPFNOSUPPORT", "EAFNOSUPPORT", "EADDRINUSE", "EADDRNOTAVAIL", "ENETDOWN", "ENETUNREACH", "ENETRESET", "ECONNABORTED",
         "ECONNRESET", "ENOBUFS", "EISCONN", "ENOTCONN", "ESHUTDOWN", "ETOOMANYREFS", "ETIMEDOUT", "ECONNREFUSED", "EHOSTDOWN",
         "EHOSTUNREACH", "EALREADY", "EINPROGRESS", "ESTALE", "EDQUOT", "ECANCELED", "EOWNERDEAD", "ENOTRECOVERABLE"]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gen_linux_abi.py <out header>", file=sys.stderr)
        return 2
    names = set(EXTRA) | set(ERRNO)
    sources = []
    for d in SOURCE_DIRS:
        folder = os.path.join(HERE, "..", d)
        sources += [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith((".cpp", ".h"))]
    for source in sources:
        with open(source, encoding="utf-8") as f:
            text = f.read()
        names |= set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", text))
        names |= set(re.findall(r"\b(__NR_[a-z0-9_]+)\b", text))
    # The system call numbers of every call the layer may be asked for by number, from the core's own list.
    # Pointers in disguise, which the layer leaves to the C library's own header; and the C library's own limits and
    # numbers (LONG_MAX, CLOCKS_PER_SEC, EOF, ...), which describe the host's C library and must keep its values.
    # The fixed-width integers' limits (INT64_MIN, UINT32_MAX, ...) are the C library's too.
    host_own = re.compile(r"^((S|U)?CHAR|U?SHRT|U?INT(8|16|32|64)?|U?INT_(LEAST|FAST)(8|16|32|64)|U?LONG|U?LLONG|WCHAR|S?SIZE|PTRDIFF|U?INTPTR|U?INTMAX|SIG_ATOMIC|WINT)"
                          r"_(MAX|MIN|BIT|WIDTH)$|^(CHAR_BIT|MB_LEN_MAX|CLOCKS_PER_SEC|RAND_MAX|EOF|BUFSIZ|FILENAME_MAX|FOPEN_MAX|L_tmpnam|TMP_MAX|"
                          r"EXIT_SUCCESS|EXIT_FAILURE)$")
    names = sorted(n for n in names - {"SIG_DFL", "SIG_IGN", "SIG_ERR"} if not host_own.match(n))
    lines = ["#define _GNU_SOURCE", *[f"#include <{h}>" for h in HEADERS], "#include <stdio.h>", "int main(void) {"]
    for n in names:
        # Only names the system defines as numbers: strings and pointers (ELFMAG, MAP_FAILED) and anything else (a
        # macro of the core's, a function) are left.
        lines.append(f"#if defined({n})\n  if (_Generic(({n}), char*: 0, const char*: 0, void*: 0, default: 1)) printf(\"#define {n} %lld\\n\", (long long)({n}));\n#endif")
    lines.append("  return 0;\n}")
    # The system's C compiler, by either of its usual names.
    compiler = next((c for c in ("cc", "clang", "gcc") if shutil.which(c)), None)
    if not compiler:
        print("gen_linux_abi.py: no C compiler", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "abi.c")
        exe = os.path.join(tmp, "abi")
        with open(src, "w", encoding="ascii") as f:
            f.write("\n".join(lines) + "\n")
        # Names that are defined but are not numbers (strings, function-like macros) fail to compile: dropped one by
        # one until it builds.
        while True:
            r = subprocess.run([compiler, "-w", "-o", exe, src], capture_output=True, text=True)
            if r.returncode == 0:
                break
            bad = set(re.findall(r"abi\.c:(\d+):", r.stderr))
            if not bad:
                print(r.stderr, file=sys.stderr)
                return 1
            with open(src, encoding="ascii") as f:
                body = f.read().split("\n")
            for line_no in sorted((int(b) for b in bad), reverse=True):
                # The failing printf line and its #if/#endif pair.
                if 2 <= line_no <= len(body) and body[line_no - 1].lstrip().startswith("if (_Generic"):
                    del body[line_no - 2:line_no + 1]
            with open(src, "w", encoding="ascii") as f:
                f.write("\n".join(body))
        out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout
    with open(sys.argv[1], "w", encoding="ascii") as f:
        f.write("// Linux's numbers on x86-64 for the runtime's layer on hosts without them (arm32/src/win/include/arm32_linux.h).\n")
        f.write("// Generated by arm32/tools/gen_linux_abi.py from a Linux x86-64 system's headers; not edited by hand.\n")
        f.write("#pragma once\n\n")
        for line in out.splitlines():
            name = line.split()[1]
            f.write(f"#undef {name}\n{line}\n")
    print(f"gen_linux_abi.py: {len(out.splitlines())} numbers in {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
