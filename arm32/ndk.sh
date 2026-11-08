# shellcheck shell=sh
# Sourced by build.sh and bundle.sh: sets ndk to the Android NDK to use, for someone who has never heard of one too.
# $here and $work are the caller's (arm32/ and _work/arm32); bundle.sh sets work before it sources this.
ndk_url=https://dl.google.com/android/repository/android-ndk-r25c-linux.zip
ndk_sha1=53af80a1cce9144025b81c78c8cd556bff42bd0e

find_ndk() {
    # Asked for by name, or one that is there already.
    ndk=${ANDROID_NDK:-$(ls -d "$HOME"/android-sdk/ndk/* "$work"/ndk/android-ndk-* 2>/dev/null | sort -V | tail -n 1)}
    [ -n "$ndk" ] && [ -d "$ndk" ] && return 0
    # None: once, in a container, since a host may have neither curl nor unzip. About 600 MB, 2 GB unpacked.
    echo "arm32: fetching the Android NDK (once; about 600 MB)" >&2
    mkdir -p "$work/ndk"
    docker run --rm --platform linux/amd64 -u "$(id -u):$(id -g)" -v "$work/ndk:/n" opendmtq-arm32-dev:local sh -ec "
      cd /n
      # Interrupted earlier: over again. Unpacked aside, so that only a whole NDK ever has the name looked for above.
      rm -rf part ndk.zip
      # A download that stalls (under 100 KB/s for a minute) is cut and tried again, rather than waiting for ever.
      curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --speed-limit 100000 --speed-time 60 -o ndk.zip $ndk_url
      echo '$ndk_sha1  ndk.zip' | sha1sum -c --quiet -
      mkdir part
      unzip -q ndk.zip -d part
      mv part/android-ndk-* .
      rm -rf part ndk.zip"
    ndk=$(ls -d "$work"/ndk/android-ndk-* | sort -V | tail -n 1)
}

# jni.h from the NDK, alone in $work/jni-include with Android's android/ and SLES/ headers (the NDK's other headers are
# Android's C library and would shadow the host's): the Java VM in arm32/jvm implements JNI with the same types as on a
# phone, the player's NDK functions (arm32/desktop/ndk.cpp) take libandroid's declarations and constants, and its sound
# bridge is written against OpenSL ES's. For the builds for computers (build_desktop.sh, build_windows.sh), after find_ndk.
jni_headers() {
    jni_h=$(ls "$ndk"/toolchains/llvm/prebuilt/*/sysroot/usr/include/jni.h | head -n 1)
    mkdir -p "$work/jni-include"
    cp "$jni_h" "$work/jni-include/jni.h"
    # Whole folders again: a header gone from a newer NDK goes here too.
    rm -rf "$work/jni-include/android" "$work/jni-include/SLES"
    cp -r "$(dirname "$jni_h")/android" "$work/jni-include/android"
    cp -r "$(dirname "$jni_h")/SLES" "$work/jni-include/SLES"
}
