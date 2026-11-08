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
# jni.h from the NDK the Android build uses, alone in a folder of its own (the NDK's other headers are Android's C
# library and would shadow the host's): the Java VM in arm32/jvm implements it, with the same types as on a phone.
work=$root/_work/arm32
. "$here/ndk.sh"
find_ndk
jni_h=$(ls "$ndk"/toolchains/llvm/prebuilt/*/sysroot/usr/include/jni.h | head -n 1)
mkdir -p "$work/jni-include"
cp "$jni_h" "$work/jni-include/jni.h"
# The NDK's android/ headers too: the runtime's Android bridge calls libandroid's functions, which the player
# implements for the desktop (arm32/desktop/ndk.cpp) with these declarations and constants.
rm -rf "$work/jni-include/android" "$work/jni-include/SLES"
cp -r "$(dirname "$jni_h")/android" "$work/jni-include/android"
# And the OpenSL ES headers, which the sound bridge is written against.
cp -r "$(dirname "$jni_h")/SLES" "$work/jni-include/SLES"
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
