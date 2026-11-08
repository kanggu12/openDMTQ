# Cross-build environment for the arm32 runtime on Windows x64, on Linux: llvm-mingw (Clang, LLD, libc++ and the
# Universal C Runtime, for x86_64-w64-mingw32), CMake and Ninja, and the Boost headers Dynarmic wants.
FROM ubuntu:24.04
# One layer, and no package lists kept.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      cmake ninja-build python3 git file make libboost-dev ca-certificates curl xz-utils zstd && \
    rm -rf /var/lib/apt/lists/*
# A release a month old, at a fixed hash: the toolchain decides what every Windows build contains.
ARG LLVM_MINGW=llvm-mingw-20261006-ucrt-ubuntu-22.04-x86_64
ARG LLVM_MINGW_SHA256=5f9c6ed95b2d4bdb2869a488c5fd5857fbdabcf288a0aa3eb1da43f6a08d8ab4
RUN curl -fsSL -o /tmp/llvm-mingw.tar.xz https://github.com/mstorsjo/llvm-mingw/releases/download/20261006/$LLVM_MINGW.tar.xz && \
    echo "$LLVM_MINGW_SHA256  /tmp/llvm-mingw.tar.xz" | sha256sum -c --quiet - && \
    tar -xJf /tmp/llvm-mingw.tar.xz -C /opt && mv /opt/$LLVM_MINGW /opt/llvm-mingw && rm /tmp/llvm-mingw.tar.xz
ENV PATH=/opt/llvm-mingw/bin:$PATH
# The Boost headers alone in a folder of their own: /usr/include would put the host's C library before Windows'.
RUN mkdir -p /opt/boost/include && ln -s /usr/include/boost /opt/boost/include/boost
# The repository is mounted here.
WORKDIR /r
