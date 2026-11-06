# Build environment for the arm32 runtime: CMake, Ninja, Boost headers, and the tools that unpack
# the guest system libraries. The Android NDK is mounted at /ndk.
FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      cmake ninja-build python3 git file make libboost-dev ca-certificates curl unzip e2fsprogs \
      openjdk-17-jdk-headless && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /opt/boost/include && ln -s /usr/include/boost /opt/boost/include/boost
WORKDIR /r
