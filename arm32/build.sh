#!/bin/sh
# Builds the arm32 runner for one host ABI, and the 32-bit guest test programs, in a container.
#
#   arm32/build.sh [arm64-v8a|x86_64]
#
# Needs Docker. The Android NDK is ANDROID_NDK, or the newest one under ~/android-sdk/ndk, or fetched once into
# _work/arm32/ndk. The JNI test also wants an SDK with build-tools and a platform (ANDROID_HOME, or ~/android-sdk).
# On first use it fetches Dynarmic and the 32-bit system libraries of the AOSP Android 6.0
# image into _work/arm32.
set -eu
abi=${1:-arm64-v8a}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
work=$repo/_work/arm32
. "$here/ndk.sh"
sdk=${ANDROID_HOME:-$HOME/android-sdk}
dynarmic_url=https://github.com/azahar-emu/dynarmic
dynarmic_commit=a46601580d5512d324104f985b5f0209dc980ddc
image_url=https://dl.google.com/android/repository/sys-img/android/armeabi-v7a-23_r06.zip
image_sha1=7cf2ad756e54a3acfd81064b63cb0cb9dff2798d

mkdir -p "$work"
# The NDK's compilers are x86-64 programs: all of this runs as x86-64, emulated on an ARM machine.
docker build -q --platform linux/amd64 -t opendmtq-arm32-dev:local "$here" >/dev/null
find_ndk
# The SDK only when it is there (only the JNI test needs it): docker run -v makes a missing folder,
# as root, which would leave a root-owned ~/android-sdk the user cannot install the SDK into.
run() {
    if [ -d "$sdk" ]; then
        docker run --rm --platform linux/amd64 -u "$(id -u):$(id -g)" -v "$repo:/r" -v "$ndk:/ndk:ro" -v "$sdk:/sdk:ro" opendmtq-arm32-dev:local sh -ec "$1"
    else
        docker run --rm --platform linux/amd64 -u "$(id -u):$(id -g)" -v "$repo:/r" -v "$ndk:/ndk:ro" opendmtq-arm32-dev:local sh -ec "$1"
    fi
}

# Dynarmic at a known commit. A clone or fetch that stalls (under 1 KB/s for a minute) stops rather than waiting for ever.
export GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=60
[ -d "$work/dynarmic/.git" ] || git clone -q --recursive "$dynarmic_url" "$work/dynarmic"
git -C "$work/dynarmic" checkout -q "$dynarmic_commit"
git -C "$work/dynarmic" submodule update -q --init --recursive
# Local changes to Dynarmic, each applied once.
for patch in "$here"/patches/*.patch; do
    git -C "$work/dynarmic" apply --check -R "$patch" 2>/dev/null || git -C "$work/dynarmic" apply "$patch"
done

# Guest system libraries: the 32-bit linker and libraries of the AOSP Android 6.0 image.
if [ ! -f "$work/sysroot/lib/libc.so" ] || [ ! -f "$work/sysroot/NOTICE.html.gz" ]; then
    run "
      cd _work/arm32
      # Under its name only when whole; a damaged one goes, or every later run would stop here.
      # A stalled download (under 100 KB/s for a minute) is cut and tried again.
      [ -f image.zip ] || { curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --speed-limit 100000 --speed-time 60 \
        -o image.zip.part $image_url && mv image.zip.part image.zip; }
      echo '$image_sha1  image.zip' | sha1sum -c --quiet - || { rm -f image.zip; exit 1; }
      unzip -o -q image.zip armeabi-v7a/system.img
      mkdir -p sysroot/lib sysroot/bin
      for f in libc.so libm.so libdl.so libstdc++.so libz.so liblog.so libc++.so; do
        debugfs -R \"dump /lib/\$f sysroot/lib/\$f\" armeabi-v7a/system.img 2>/dev/null
      done
      debugfs -R 'dump /bin/linker sysroot/bin/linker' armeabi-v7a/system.img 2>/dev/null
      # Their licenses, which go with the app (bundle.sh).
      debugfs -R 'dump /etc/NOTICE.html.gz sysroot/NOTICE.html.gz' armeabi-v7a/system.img 2>/dev/null
      rm -rf armeabi-v7a image.zip"
fi

# Bridge sources generated from the NDK headers and the stub lists, and the guest's stub
# libraries built from them (they join the guest system libraries).
run "
  inc=/ndk/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include
  gen=_work/arm32/gen
  mkdir -p \$gen
  python3 arm32/tools/gen_gl.py \$inc \$gen 2>/dev/null
  python3 arm32/tools/gen_stubs.py arm32/guest/libEGL.list 0x100000 0x201000 \$gen/egl.S \$gen/egl_numbers.h kEgl_
  python3 arm32/tools/gen_stubs.py arm32/guest/libandroid.list 0x102000 0x201100 \$gen/android.S \$gen/android_numbers.h kAndroid_
  python3 arm32/tools/gen_stubs.py arm32/guest/libOpenSLES.list 0x103000 0x201200 \$gen/opensl.S \$gen/opensl_numbers.h kSl_
  cc=/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi21-clang
  lib=_work/arm32/sysroot/lib
  \$cc -shared -nostdlib -Wl,-soname,libEGL.so -o \$lib/libEGL.so \$gen/egl.S
  \$cc -shared -nostdlib -Wl,-soname,libGLESv2.so -o \$lib/libGLESv2.so \$gen/gl_stubs.S
  \$cc -shared -nostdlib -Wl,-soname,libGLESv3.so -o \$lib/libGLESv3.so \$gen/gl_stubs.S
  \$cc -shared -nostdlib -Wl,-soname,libandroid.so -o \$lib/libandroid.so \$gen/android.S
  \$cc -shared -nostdlib -Wl,-soname,libOpenSLES.so -o \$lib/libOpenSLES.so \$gen/opensl.S"

# The runner and the app libraries. API 21 is the oldest 64-bit Android: a universal APK lands on
# the runtime there too, since use32bitAbi (API 24) is what sends 32-bit-capable phones to the
# game's own libraries. Newer platform functions are looked up at run time.
run "
  cmake -S arm32 -B _work/arm32/build-$abi -G Ninja -DCMAKE_TOOLCHAIN_FILE=/ndk/build/cmake/android.toolchain.cmake \
    -DANDROID_ABI=$abi -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release \
    -DDYNARMIC_DIR=/r/_work/arm32/dynarmic -DARM32_GEN_DIR=/r/_work/arm32/gen -DBoost_INCLUDE_DIR=/opt/boost/include \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH >/dev/null
  ninja -C _work/arm32/build-$abi arm32run arm32 arm32proxy > _work/arm32/ninja-$abi.log || { tail -n 40 _work/arm32/ninja-$abi.log >&2; exit 1; }"

# The shim for phones that run the game's own 32-bit libraries (shim/shim.cpp).
run "
  cmake -S arm32/shim -B _work/arm32/build-shim -G Ninja -DCMAKE_TOOLCHAIN_FILE=/ndk/build/cmake/android.toolchain.cmake \
    -DANDROID_ABI=armeabi-v7a -DANDROID_PLATFORM=android-21 -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release >/dev/null
  ninja -C _work/arm32/build-shim opendmtq > _work/arm32/ninja-shim.log || { tail -n 40 _work/arm32/ninja-shim.log >&2; exit 1; }"

# Guest test programs, 32-bit ARM.
run "
  cc=/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi21-clang
  out=_work/arm32/guest t=arm32/tests
  mkdir -p \$out
  \$cc -O2 -o \$out/basic \$t/basic.c -lm
  \$cc -O2 -o \$out/signals \$t/signals.c
  \$cc -O2 -o \$out/interrupt \$t/interrupt.c
  \$cc -O2 -o \$out/wakes \$t/wakes.c
  \$cc -O2 -o \$out/restart \$t/restart.c
  \$cc -O2 -o \$out/coherence \$t/coherence.c
  \$cc -O2 -o \$out/memory \$t/memory.c
  \$cc -O2 -o \$out/calls \$t/calls.c
  \$cc -O2 -o \$out/guard \$t/guard.c
  \${cc}++ -O2 -static-libstdc++ -o \$out/cxx \$t/cxx.cpp
  \$cc -O2 -mfpu=neon -o \$out/neon \$t/neon.c -lm
  \$cc -O2 -shared -fPIC -o \$out/libplugin.so \$t/plugin.c
  \$cc -O2 -o \$out/dl \$t/dl.c
  \$cc -O2 -o \$out/arm32-agent arm32/guest/agent.c arm32/guest/traps.S
  \$cc -O2 -shared -fPIC -o \$out/libarm32g-libjnitest.so \$t/jni/jnitest.c \$t/jni/media.c -lEGL -lGLESv3 -lOpenSLES
  \$cc -O2 -mfpu=neon -o \$out/bench \$t/bench.c
  /ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang -O2 -fno-vectorize -fno-slp-vectorize -o \$out/bench-native \$t/bench.c"
# The Java side of the JNI test, as dex for app_process. Needs an SDK platform and build-tools;
# without them only that test is left out (the runtime does not need it).
run "
  platform=\$(ls -d /sdk/platforms/android-* 2>/dev/null | sort -V | tail -n 1)
  tools=\$(ls -d /sdk/build-tools/* 2>/dev/null | sort -V | tail -n 1)
  if [ -z \"\$platform\" ] || [ ! -f \"\$tools/lib/d8.jar\" ]; then
    echo 'no Android SDK platform and build-tools: the JNI test is not built (set ANDROID_HOME)'
    exit 0
  fi
  rm -rf _work/arm32/jni-classes && mkdir -p _work/arm32/jni-classes
  javac -nowarn -source 8 -target 8 -cp \$platform/android.jar -d _work/arm32/jni-classes arm32/tests/jni/Arm32JniTest.java
  java -cp \$tools/lib/d8.jar com.android.tools.r8.D8 --min-api 26 --output _work/arm32/jni-classes _work/arm32/jni-classes/Arm32JniTest.class
  mv _work/arm32/jni-classes/classes.dex _work/arm32/guest/jnitest.dex"
echo "built _work/arm32/build-$abi (arm32run, libarm32.so, libarm32proxy.so) and the guest tests in _work/arm32/guest"
