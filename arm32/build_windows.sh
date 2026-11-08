#!/bin/sh
# Builds the runtime for Windows x64 on Linux, in a container with llvm-mingw (arm32/windows.Dockerfile).
#
#   arm32/build_windows.sh [targets...]      (default: arm32run)
#
# The Android build (arm32/build.sh) fetches Dynarmic into _work/arm32/dynarmic and copies jni.h; run it once first.
# The programs land in _work/arm32/build-windows-x86_64.
set -eu
# The repository, wherever this script is called from.
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
[ -f "$root/_work/arm32/dynarmic/CMakeLists.txt" ] || { echo "no Dynarmic in _work/arm32/dynarmic: run arm32/build.sh once" >&2; exit 1; }
# jni.h and Android's headers from the NDK the Android build uses, for the Java VM and the player, as the build for a
# desktop Linux host has them (ndk.sh): a fresh checkout, as CI's, has only what arm32/build.sh made.
work=$root/_work/arm32
. "$here/ndk.sh"
find_ndk
jni_headers
targets=${*:-arm32run}
# The common standard headers before every C++ file: Dynarmic and its fmt (11.1.4) use std::vector, malloc and others
# without including them, which older libc++ (the NDK's) and glibc's headers bring in on the way and llvm-mingw's newer
# libc++ no longer does.
cxx_flags='-include cstdlib -include vector -include string -include algorithm -include memory -include optional -include functional -include cstring'
# The build image, made again only when its file changed (Docker's cache).
docker build -q -t opendmtq-arm32-windows -f "$here/windows.Dockerfile" "$here" >/dev/null
# What the player needs on Windows that the toolchain does not have, from MSYS2's UCRT packages at fixed hashes: ANGLE
# (OpenGL ES and EGL on Direct3D 11), the Khronos EGL and GLES headers, zlib, and the GCC runtime ANGLE's DLLs were
# built with. Fetched once into _work/arm32/win-deps (include, lib, bin); the DLLs go beside the player.
deps=_work/arm32/win-deps
msys=https://mirror.msys2.org/mingw/ucrt64
packages="
mingw-w64-ucrt-x86_64-angleproject-2.1.r25748.890b5d8f-6-any.pkg.tar.zst 3c184061a3a3ef6478055e11eb786e20c40e62c1c239a1d65bf1399b7e2e7113
mingw-w64-ucrt-x86_64-egl-headers-1.5.r284.3ae2b7c-1-any.pkg.tar.zst 29743159048cf216f75d0dc3eb3e0a04a07515db17d839803e54b060f5aeb0b3
mingw-w64-ucrt-x86_64-gles-headers-3.2.r1065.7fc154c-1-any.pkg.tar.zst 066007a50bd08f062b5494f2c4811a219e1a65f4ecdce2beb453f6d9d8b92098
mingw-w64-ucrt-x86_64-libgcc-16.2.0-6-any.pkg.tar.zst 80b2497f019977dd9528b1abc8621b1328a0115ab1f724047ccbb56bf323f11d
mingw-w64-ucrt-x86_64-libstdc++-16.2.0-6-any.pkg.tar.zst 33c5e58a85a538cf843a8672991cce591f0231d66da3b66a57629712d64be17f
mingw-w64-ucrt-x86_64-libwinpthread-14.0.0.r598.ge3d18511f-1-any.pkg.tar.zst c35d6be83d141c8cfbb61f1637dd4b53aac8f5562d766aa26d0741c40bad4e4d
mingw-w64-ucrt-x86_64-zlib-1.4-2-any.pkg.tar.zst 172541cf5e2391a402f092104988699b0163129d22be1d6b4b201bfb84af6fcf
"
# The stamp is the hash of the list and of this script's copying (its version, below): either changing fetches again.
copy_version=2
if [ ! -f "$root/$deps/.done" ] || [ "$(cat "$root/$deps/.done")" != "$(echo "$packages $copy_version" | sha256sum)" ]; then
  docker run --rm -u "$(id -u):$(id -g)" -v "$root:/r" -w /r opendmtq-arm32-windows sh -ec "
    rm -rf $deps && mkdir -p $deps/pkgs $deps/include $deps/lib $deps/bin $deps/licenses
    echo '$packages' | while read -r file sum; do
      [ -n \"\$file\" ] || continue
      curl -fsSL --retry 3 --connect-timeout 30 -o $deps/pkgs/\$file $msys/\$file
      echo \"\$sum  $deps/pkgs/\$file\" | sha256sum -c --quiet -
      mkdir -p $deps/x && tar --zstd -xf $deps/pkgs/\$file -C $deps/x ucrt64
    done
    # The headers, the import library of zlib's zlib1.dll (ANGLE's own needs it: the player uses the same), the DLLs the
    # player loads or ANGLE's need, and their licenses. KHR/khrplatform.h is the toolchain's own (mingw-w64's headers
    # have it).
    cp -r $deps/x/ucrt64/include/EGL $deps/x/ucrt64/include/GLES2 $deps/x/ucrt64/include/GLES3 $deps/include/
    cp $deps/x/ucrt64/include/zlib.h $deps/x/ucrt64/include/zconf.h $deps/include/
    cp $deps/x/ucrt64/lib/libzlib1.dll.a $deps/lib/
    for dll in libEGL.dll libGLESv2.dll zlib1.dll libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll; do cp $deps/x/ucrt64/bin/\$dll $deps/bin/; done
    cp -r $deps/x/ucrt64/share/licenses/. $deps/licenses/
    rm -rf $deps/x $deps/pkgs"
  echo "$packages $copy_version" | sha256sum > "$root/$deps/.done"
fi
docker run --rm -v "$root:/r" -w /r opendmtq-arm32-windows sh -c "
  cmake -S arm32 -B _work/arm32/build-windows-x86_64 -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_SYSTEM_NAME=Windows \
    -DCMAKE_C_COMPILER=x86_64-w64-mingw32-clang -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-clang++ \
    -DCMAKE_RC_COMPILER=x86_64-w64-mingw32-windres -DDYNARMIC_DIR=/r/_work/arm32/dynarmic -DBoost_INCLUDE_DIR=/opt/boost/include \
    -DJNI_INCLUDE_DIR=/r/_work/arm32/jni-include -DARM32_GEN_DIR=/r/_work/arm32/gen -DWIN_DEPS=/r/$deps -DCMAKE_CXX_FLAGS='$cxx_flags' >/dev/null
  cmake --build _work/arm32/build-windows-x86_64 --target $targets
"
echo "built $targets in _work/arm32/build-windows-x86_64"
