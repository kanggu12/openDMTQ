#!/bin/sh
# Packs the player for Windows without an app: opendmtq-player-windows.zip, which the PC client's installer carries
# (client/packaging/windows/build.sh). The client starts it with a server's app (player --app, the APK and player.conf
# naming it); arm32/desktop/own_folder.cpp says what the player expects there.
#
#   arm32/bundle_windows.sh [out zip]      (default _work/arm32/opendmtq-player-windows.zip)
#
# Needs the guest's system and the agent (arm32/build.sh) and the player (arm32/build_windows.sh player). The zip holds
# one folder, OpenDMTQ-Player, and bundle.json beside it with its version.
set -eu
# The repository, wherever this script is called from.
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
out=${1:-$root/_work/arm32/opendmtq-player-windows.zip}
work=$root/_work/arm32
build=$work/build-windows-x86_64
deps=$work/win-deps
[ -f "$build/player.exe" ] || { echo "no player: run arm32/build_windows.sh player" >&2; exit 1; }
[ -f "$work/guest/arm32-agent" ] && [ -f "$work/sysroot/bin/linker" ] || { echo "no guest system: run arm32/build.sh" >&2; exit 1; }
# A fresh folder to lay it out in.
stage=$work/player-windows
rm -rf "$stage"
mkdir -p "$stage/OpenDMTQ-Player/runtime" "$stage/OpenDMTQ-Player/licenses"
dest=$stage/OpenDMTQ-Player
# The player without its symbols (a quarter of its size), by the toolchain's own strip; ANGLE's DLLs and those they need.
docker run --rm -u "$(id -u):$(id -g)" -v "$root:/r" opendmtq-arm32-windows \
  llvm-strip --strip-unneeded -o /r/_work/arm32/player-windows/OpenDMTQ-Player/OpenDMTQ-Player.exe /r/_work/arm32/build-windows-x86_64/player.exe
for dll in libEGL.dll libGLESv2.dll zlib1.dll libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll; do
  cp "$deps/bin/$dll" "$dest/"
done
# The guest's system: its linker, libraries and time zones; and the agent.
mkdir -p "$dest/runtime/sysroot"
cp -R "$work/sysroot/bin" "$work/sysroot/lib" "$work/sysroot/usr" "$dest/runtime/sysroot/"
cp "$work/guest/arm32-agent" "$dest/runtime/"
cp "$here/desktop/README-windows.txt" "$dest/README.txt"
# The licenses of every part, one file, in the order NOTICES-windows.txt names them; Android's notices beside it.
notice() {
  printf '\n\n---- %s\n\n' "$1"
  cat "$2"
}
{
  cat "$here/desktop/NOTICES-windows.txt"
  notice OpenDMTQ "$root/LICENSE"
  notice Dynarmic "$work/dynarmic/LICENSE.txt"
  for part in fmt/LICENSE mcl/LICENSE robin-map/LICENSE xbyak/COPYRIGHT zycore/LICENSE zydis/LICENSE; do
    notice "$(dirname "$part")" "$work/dynarmic/externals/$part"
  done
  # The picture's passes (arm32/desktop/post_pass.cpp, cmaa2.cpp): their authors' licenses, as their sources carry them.
  notice "AMD FidelityFX Super Resolution 1" "$here/desktop/third_party/fsr/license.txt"
  notice "NVIDIA Image Scaling SDK" "$here/desktop/third_party/nis/licence.txt"
  notice "SMAA" "$here/desktop/third_party/smaa/LICENSE.txt"
  notice "CMAA 2" "$here/desktop/third_party/cmaa2/license.txt"
} > "$dest/licenses/NOTICES.txt"
# The toolchain's licenses come out of its image.
docker run --rm -v "$here:/a:ro" opendmtq-arm32-windows sh -ec '
  m=/opt/llvm-mingw/x86_64-w64-mingw32/share/mingw32
  printf "\n\n---- LLVM (libc++, libc++abi, libunwind, compiler-rt)\n\n"; cat /opt/llvm-mingw/LICENSE.TXT
  printf "\n\n---- mingw-w64 runtime\n\n"; cat $m/COPYING.MinGW-w64-runtime.txt
  printf "\n\n---- winpthreads\n\n"; cat $m/COPYING.winpthreads.txt
' >> "$dest/licenses/NOTICES.txt"
{
  notice "ANGLE" "$deps/licenses/angleproject/LICENSE"
  notice "zlib" "$deps/licenses/zlib/LICENSE"
  notice "GCC Runtime Library Exception" "$deps/licenses/libgcc/COPYING.RUNTIME"
  notice "GNU General Public License 3 (the GCC runtime's)" "$deps/licenses/libgcc/COPYING3"
  notice "libc++ (Android's, in runtime/sysroot)" "$here/libc++-LICENSE.txt"
} >> "$dest/licenses/NOTICES.txt"
cp "$work/sysroot/NOTICE.html.gz" "$dest/licenses/android-NOTICE.html.gz"
# The version: the commit, and a hash of the files, which changes with any change to them, even between commits.
digest=$(cd "$stage" && find OpenDMTQ-Player -type f | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -c1-8)
commit=$(git -C "$root" describe --always --dirty 2>/dev/null || echo unknown)
printf '{"version": "%s-%s", "built_at": "%s"}\n' "$commit" "$digest" "$(date +%Y-%m-%dT%H:%M:%S)" > "$stage/bundle.json"
# The zip: its files in a fixed order and a fixed time, so that the same files make the same zip; the programs with the
# permissions Windows' own extraction ignores and a Linux unzip keeps.
mkdir -p "$(dirname "$out")"
python3 -c '
import os, sys, zipfile
stage, out = sys.argv[1], sys.argv[2]
names = sorted(os.path.relpath(os.path.join(d, f), stage) for d, _, fs in os.walk(stage) for f in fs)
with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for name in names:
        info = zipfile.ZipInfo(name.replace(os.sep, "/"), (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o755 if name.endswith((".exe", ".dll", "arm32-agent", "linker")) else 0o644) << 16
        with open(os.path.join(stage, name), "rb") as f:
            z.writestr(info, f.read())
os.replace(out + ".part", out)
' "$stage" "$out"
echo "bundle_windows: $out ($commit-$digest, $(du -h "$out" | cut -f1))"
