# The tools that build the Windows bundle on Linux (host/windows/build.sh): MinGW-w64 for OpenDMTQ.exe, binutils to read
# the programs' DLL imports, pip to fetch the Windows wheels, 7-Zip for the 7-Zip installer, zip for the bundle.
FROM debian:12
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
       gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64 python3 python3-pip 7zip zip unzip curl ca-certificates \
       >/dev/null \
    && rm -rf /var/lib/apt/lists/*
