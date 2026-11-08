#!/bin/sh
# Builds the runtime's core and its command-line runner for a desktop Linux host (x86-64, glibc), in a container.
#
#   arm32/build_desktop.sh
#
# The Android build (arm32/build.sh) fetches Dynarmic into _work/arm32/dynarmic; run it once first. The runner lands in
# _work/arm32/build-desktop-x86_64/arm32run; arm32/test_desktop.sh runs the guest tests with it.
set -eu
# The repository, wherever this script is called from.
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
# Dynarmic comes from the Android build's checkout: one copy, one version.
[ -f "$root/_work/arm32/dynarmic/CMakeLists.txt" ] || { echo "no Dynarmic in _work/arm32/dynarmic: run arm32/build.sh once" >&2; exit 1; }
# jni.h and Android's headers from the NDK the Android build uses, for the Java VM and the player (ndk.sh).
work=$root/_work/arm32
. "$here/ndk.sh"
find_ndk
jni_headers
# The bridges' generated sources (GL thunks, stub numbers) come from the Android build.
[ -f "$work/gen/gl_thunks.cpp" ] || { echo "no generated bridge sources in _work/arm32/gen: run arm32/build.sh once" >&2; exit 1; }
# The build image, made again only when its file changed (Docker's cache).
docker build -q -t opendmtq-arm32-desktop -f "$here/desktop.Dockerfile" "$here" >/dev/null
# Configure and build the runner, the tests of the Java VM, the mixer and the video path, and the desktop player: the app
# library is Android's
# (arm32/CMakeLists.txt stops before it here).
docker run --rm -v "$root:/r" -w /r opendmtq-arm32-desktop sh -c '
  cmake -S arm32 -B _work/arm32/build-desktop-x86_64 -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DDYNARMIC_DIR=/r/_work/arm32/dynarmic \
    -DJNI_INCLUDE_DIR=/r/_work/arm32/jni-include -DARM32_GEN_DIR=/r/_work/arm32/gen >/dev/null
  cmake --build _work/arm32/build-desktop-x86_64 --target arm32run jvmtest audiotest mediatest player
'
echo "built _work/arm32/build-desktop-x86_64/arm32run"
