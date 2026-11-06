#!/bin/sh
# Collects the runtime into the bundle the APK builder adds to the game for 64-bit-only phones.
#
#   arm32/bundle.sh [DIR]     (default data/apk/arm32, where the builder looks)
#
# Builds the runtime first (incrementally: a build that is up to date takes seconds), so the bundle
# always holds the current source. ARM32_BUNDLE_ABIS lists the host ABIs to include (default
# arm64-v8a; add x86_64 to try the 64-bit path on an x86_64 emulator).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
work=$root/_work/arm32
out=${1:-$root/data/apk/arm32}
abis=${ARM32_BUNDLE_ABIS:-arm64-v8a}
. "$here/ndk.sh"
# The builds below find or fetch it first; the strip tool comes from the same one.
for abi in $abis; do
    "$here/build.sh" "$abi"
done
find_ndk

# Assembled next to the old bundle and swapped in whole, so the builder never sees half of one. In the build's container:
# the NDK's strip is an x86-64 Linux program, and the hash takes tools a Mac does not have.
rm -rf "$out.new"
mkdir -p "$out.new"
# Docker takes full paths only, and DIR may be relative.
assembled=$(cd "$out.new" && pwd)
assemble='
strip=/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip
mkdir -p /o/sysroot
for abi in '"$abis"'; do
    mkdir -p "/o/$abi"
    # Without the debug information (most of the file): the phone extracts these uncompressed.
    # The unstripped builds stay in _work for symbolizing crashes.
    for lib in libarm32.so libarm32proxy.so; do
        "$strip" --strip-unneeded -o "/o/$abi/$lib" "/w/build-$abi/$lib"
    done
done
# The shim, for phones that run the game'"'"'s own 32-bit libraries.
mkdir -p /o/armeabi-v7a
"$strip" --strip-unneeded -o /o/armeabi-v7a/libopendmtq.so /w/build-shim/libopendmtq.so
cp -R /w/sysroot/bin /w/sysroot/lib /o/sysroot/
cp /w/guest/arm32-agent /o/
# The licenses that have to travel with these parts. Each ABI has its own translator back end: oaknut on arm64, xbyak and
# Zydis on x86_64 (for the emulator).
mkdir -p /o/notices
parts="dynarmic/LICENSE.txt dynarmic/externals/fmt/LICENSE dynarmic/externals/mcl/LICENSE dynarmic/externals/robin-map/LICENSE"
for abi in '"$abis"'; do
    case "$abi" in
        arm64-v8a) parts="$parts dynarmic/externals/oaknut/LICENSE" ;;
        x86_64) parts="$parts dynarmic/externals/xbyak/COPYRIGHT dynarmic/externals/zycore/LICENSE dynarmic/externals/zydis/LICENSE" ;;
    esac
done
{
    cat /a/NOTICES.txt
    printf "\n\n---- OpenDMTQ\n\n"
    cat /LICENSE
    # Android'"'"'s own notices, the image'"'"'s file, do not name libc++.
    printf "\n\n---- libc++\n\n"
    cat /a/libc++-LICENSE.txt
    for part in $parts; do
        printf "\n\n---- %s\n\n" "$(basename "$(dirname "$part")")"
        cat "/w/$part"
    done
} > /o/notices/NOTICES.txt
cp /w/sysroot/NOTICE.html.gz /o/notices/android-NOTICE.html.gz
# A hash of the bundled files: it changes with any change to them, even between commits.
cd /o && find . -type f | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -c1-8
'
digest=$(docker run --rm --platform linux/amd64 -u "$(id -u):$(id -g)" -v "$work:/w:ro" -v "$here:/a:ro" -v "$root/LICENSE:/LICENSE:ro" -v "$ndk:/ndk:ro" -v "$assembled:/o" \
    opendmtq-arm32-dev:local sh -ec "$assemble")

# The version tells the builder when the game must be packed again: the commit, and that hash.
commit=$(git -C "$root" describe --always --dirty 2>/dev/null || echo unknown)
version=$commit-$digest
list=$(for abi in $abis; do printf '"%s", ' "$abi"; done)
printf '{"version": "%s", "built_at": "%s", "abis": [%s]}\n' "$version" "$(date +%Y-%m-%dT%H:%M:%S)" "${list%, }" > "$out.new/bundle.json"
rm -rf "$out"
mv "$out.new" "$out"
echo "bundle: $out ($version, $abis)"
