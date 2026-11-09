#!/usr/bin/env bash
# Builds the Windows bundle, OpenDMTQ-windows.zip, on Linux: the programs it brings (Apache, PHP, Python, Java, 7-Zip, the
# Android tools), each pinned to the file that was tested by its SHA-256, OpenDMTQ's own code, and OpenDMTQ.exe compiled
# with MinGW-w64. It runs in a container with the tools it needs (host/windows/Dockerfile), and checks at the end that
# every program in the bundle finds the DLLs it needs there or in Windows itself.
#
# Usage: host/windows/build.sh [out folder]      (default _work/windows; VERSION=1.2.3 for a release, else date-commit)
#
# Apache Lounge keeps only its newest build for download, and PHP moves older builds: each file is also kept in this
# repository's release named build-inputs, where the build falls back to. To move to a newer one, test the bundle
# with it, put its name and hash below, and add it there under the same name:
# gh release upload build-inputs <file> --clobber
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)

# The pinned downloads: address and SHA-256 of the copy that was tested.
APACHE_URL=https://www.apachelounge.com/download/VS18/binaries/httpd-2.4.69-261002-Win64-VS18.zip
APACHE_SHA=77d715d0d9cee731e2251e7ddc2090a7a8e6d41fedef2e9827cd918593c5a652
APACHE_VERSION=2.4.69
PHP_URL=https://windows.php.net/downloads/releases/php-8.3.36-1-Win32-vs16-x64.zip
# Older PHP builds move to the archive.
PHP_ARCHIVE_URL=https://windows.php.net/downloads/releases/archives/php-8.3.36-1-Win32-vs16-x64.zip
PHP_SHA=126dd3cc8c19df5085b9420b2bc74ed591de3d98528858c52fc42739b7bba92e
PHP_VERSION=8.3.36
PYTHON_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
PYTHON_SHA=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3
PYTHON_VERSION=3.12.10
JRE_URL=https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip
JRE_SHA=2332c0b4cff6bed722da3567c91d5e47568bcba863fa4945d0a8d6fc76158628
JRE_VERSION=21.0.13+9
SEVENZIP_URL=https://www.7-zip.org/a/7z2501-x64.exe
SEVENZIP_SHA=78afa2a1c773caf3cf7edf62f857d2a8a5da55fb0fff5da416074c0d28b2b55f
SEVENZIP_VERSION=25.01
# The same Android tools as the tools image and host/install.sh.
APKTOOL_URL=https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar
APKTOOL_SHA=66cf4524a4a45a7f56567d08b2c9b6ec237bcdd78cee69fd4a59c8a0243aeafa
SIGNER_URL=https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar
SIGNER_SHA=e1299fd6fcf4da527dd53735b56127e8ea922a321128123b9c32d619bba1d835

# ------------------------------------------------------------------------------ outside: start the build container

if [ -z "${IN_BUILD_IMAGE:-}" ]; then
  OUT=$(mkdir -p "${1:-$ROOT/_work/windows}" && cd "${1:-$ROOT/_work/windows}" && pwd)
  # The version the pages and the program show: a release's, or the date and commit of this tree.
  if [ -z "${VERSION:-}" ]; then
    VERSION="$(git -C "$ROOT" log -1 --format=%cd --date=format:%Y.%m.%d)-$(git -C "$ROOT" rev-parse --short HEAD)"
  fi
  # OpenDMTQ's own files as a clone has them: those git knows, and new ones it does not ignore.
  (cd "$ROOT" && git ls-files -z --cached --others --exclude-standard -- server tools/opendmtq_tools cli/opendmtq_cli \
     host LICENSE | tar --null -T - -cf "$OUT/app.tar")
  # The runtime for newer phones, whole, when this PC has built it (a release's job does, first): the bundle then needs no
  # download for it, and no internet at all (tools/opendmtq_tools/runtime.py).
  rm -f "$OUT/opendmtq-arm32-runtime.zip"
  bundle=${ARM32_BUNDLE:-$ROOT/data/apk/arm32}
  if [ -f "$bundle/bundle.json" ]; then
    python3 "$ROOT/tools/opendmtq_tools/runtime.py" --pack "$bundle" "$OUT/opendmtq-arm32-runtime.zip"
  fi
  # The installer for Windows (the PC client), likewise, when this PC has made it (client/packaging/windows/build.sh; a
  # release's job does, first): the site then hands it to players set up for the server
  # (tools/opendmtq_tools/windows_client.py).
  rm -f "$OUT/OpenDMTQ-Setup.exe" "$OUT/OpenDMTQ-Setup.exe.version"
  if [ -f "$ROOT/tools/opendmtq_tools/OpenDMTQ-Setup.exe" ]; then
    cp "$ROOT/tools/opendmtq_tools/OpenDMTQ-Setup.exe" "$OUT/"
    [ -f "$ROOT/tools/opendmtq_tools/OpenDMTQ-Setup.exe.version" ] && cp "$ROOT/tools/opendmtq_tools/OpenDMTQ-Setup.exe.version" "$OUT/"
  fi
  docker build -q -t opendmtq-winbuild:local "$ROOT/host/windows" >/dev/null
  exec docker run --rm -e IN_BUILD_IMAGE=1 -e VERSION="$VERSION" -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$ROOT/host/windows:/build:ro" -v "$OUT:/out" opendmtq-winbuild:local bash /build/build.sh /out
fi

# ------------------------------------------------------------------------------ inside: the bundle

OUT=$1
DL=$OUT/downloads
STAGE=$OUT/OpenDMTQ
mkdir -p "$DL"
step() { printf '\n== %s\n' "$*"; }

# A download kept in the cache only when whole and when its hash is the expected one.
fetch() {
  local name=$1 sha=$2
  shift 2
  if [ -f "$DL/$name" ] && echo "$sha  $DL/$name" | sha256sum -c --quiet - 2>/dev/null; then
    return 0
  fi
  local url
  for url in "$@"; do
    # Apache Lounge answers only browsers.
    # A stalled download (under 100 KB/s for a minute) is cut and tried again, then the next address.
    if curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 30 --speed-limit 100000 --speed-time 60 \
        -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -o "$DL/$name.part" "$url"; then
      if echo "$sha  $DL/$name.part" | sha256sum -c --quiet -; then
        mv "$DL/$name.part" "$DL/$name"
        return 0
      fi
      # A maker that keeps only its newest build answers an old address with a page of its own, or another file: the
      # next address, at last this repository's own copy of the tested file.
      echo "note: $url is not the tested file (its SHA-256 differs); trying the next address" >&2
      rm -f "$DL/$name.part"
    fi
  done
  echo "error: could not download $name as tested ($*)" >&2
  exit 1
}

# This repository's copies of the tested files (the release named build-inputs), for when a maker has taken its own down.
MIRROR=https://github.com/kanggu12/openDMTQ/releases/download/build-inputs

step "Downloads"
fetch httpd.zip "$APACHE_SHA" "$APACHE_URL" "$MIRROR/httpd.zip"
fetch php.zip "$PHP_SHA" "$PHP_URL" "$PHP_ARCHIVE_URL" "$MIRROR/php.zip"
fetch python.zip "$PYTHON_SHA" "$PYTHON_URL" "$MIRROR/python.zip"
fetch jre.zip "$JRE_SHA" "$JRE_URL" "$MIRROR/jre.zip"
fetch 7zip.exe "$SEVENZIP_SHA" "$SEVENZIP_URL" "$MIRROR/7zip.exe"
fetch apktool.jar "$APKTOOL_SHA" "$APKTOOL_URL" "$MIRROR/apktool.jar"
fetch uber-apk-signer.jar "$SIGNER_SHA" "$SIGNER_URL" "$MIRROR/uber-apk-signer.jar"
echo "all checked against their SHA-256"

# A fresh bundle folder, and a scratch one for what is unpacked.
rm -rf "$STAGE" "$OUT/unpack"
mkdir -p "$STAGE/runtime" "$OUT/unpack"
RT=$STAGE/runtime

step "Apache $APACHE_VERSION"
7zz x -y -bso0 -bsp0 -o"$OUT/unpack/apache" "$DL/httpd.zip"
mkdir -p "$RT/apache/conf"
# The programs and modules, the file types, and the licenses; not the manual, the icons or the sample site.
cp -r "$OUT/unpack/apache/Apache24/bin" "$OUT/unpack/apache/Apache24/modules" "$RT/apache/"
cp "$OUT/unpack/apache/Apache24/conf/mime.types" "$RT/apache/conf/"
cp "$OUT/unpack/apache/Apache24/LICENSE.txt" "$OUT/unpack/apache/Apache24/NOTICE.txt" "$RT/apache/"
# Apache's own command line tools for other jobs (benchmarks, password files) are of no use here.
rm -f "$RT/apache/bin/"{ab,abs,htdbm,htdigest,htpasswd,httxt2dbm,logresolve,htcacheclean,ApacheMonitor,wintty}.exe

step "PHP $PHP_VERSION"
7zz x -y -bso0 -bsp0 -o"$OUT/unpack/php" "$DL/php.zip"
mkdir -p "$RT/php/ext"
# The command line, the engine, Apache's module, SQLite; the three extensions the server uses; the license.
cp "$OUT/unpack/php/"{php.exe,php8ts.dll,php8apache2_4.dll,libsqlite3.dll,license.txt} "$RT/php/"
cp "$OUT/unpack/php/ext/"{php_sqlite3.dll,php_mbstring.dll,php_opcache.dll} "$RT/php/ext/"

step "Python $PYTHON_VERSION"
7zz x -y -bso0 -bsp0 -o"$RT/python" "$DL/python.zip"
# Where the bundle's Python finds modules: its own, the libraries below, and OpenDMTQ's tools and command line.
cat > "$RT/python/python312._pth" <<'PTH'
python312.zip
.
Lib\site-packages
..\..\app\tools
..\..\app\cli
PTH
pip install -q --root-user-action=ignore --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 \
  --require-hashes -r /build/requirements.txt --target "$RT/python/Lib/site-packages"
echo "$(find "$RT/python/Lib/site-packages" -maxdepth 1 -name "*.dist-info" | wc -l) libraries"
# Apache and PHP need the same Microsoft C runtime Python brings: a copy beside each, so no installer is needed.
cp "$RT/python/vcruntime140.dll" "$RT/python/vcruntime140_1.dll" "$RT/apache/bin/"
cp "$RT/python/vcruntime140.dll" "$RT/python/vcruntime140_1.dll" "$RT/php/"

step "Java $JRE_VERSION"
7zz x -y -bso0 -bsp0 -o"$OUT/unpack/jre" "$DL/jre.zip"
mv "$OUT/unpack/jre/"*/ "$RT/java"

step "7-Zip $SEVENZIP_VERSION"
mkdir -p "$RT/7zip"
# The installer is an archive itself: only the console program, its library and the license.
7zz e -y -bso0 -bsp0 -o"$RT/7zip" "$DL/7zip.exe" 7z.exe 7z.dll License.txt readme.txt

step "Android tools"
mkdir -p "$RT/jars"
cp "$DL/apktool.jar" "$DL/uber-apk-signer.jar" "$RT/jars/"

step "OpenDMTQ $VERSION"
mkdir -p "$STAGE/app"
tar -xf "$OUT/app.tar" -C "$STAGE/app"
# The runtime for newer phones beside the code that looks for it (tools/opendmtq_tools/runtime.py).
if [ -f "$OUT/opendmtq-arm32-runtime.zip" ]; then
  cp "$OUT/opendmtq-arm32-runtime.zip" "$STAGE/app/tools/opendmtq_tools/"
fi
# The installer for Windows beside the same code, with its version (tools/opendmtq_tools/windows_client.py).
if [ -f "$OUT/OpenDMTQ-Setup.exe" ]; then
  cp "$OUT/OpenDMTQ-Setup.exe" "$STAGE/app/tools/opendmtq_tools/"
  [ -f "$OUT/OpenDMTQ-Setup.exe.version" ] && cp "$OUT/OpenDMTQ-Setup.exe.version" "$STAGE/app/tools/opendmtq_tools/"
fi
# Not the test folders: the bundle runs the code, CI tests it.
rm -rf "$STAGE/app/tools/tests" "$STAGE/app/cli/tests" "$STAGE/app/host/windows"
# The site's document root, empty (git keeps no empty folder; the image makes its own).
mkdir -p "$STAGE/app/server/game/public"
printf '%s\n' "$VERSION" > "$STAGE/app/VERSION"
cp "$STAGE/app/LICENSE" "$STAGE/LICENSE.txt"
cp /build/README.txt "$STAGE/README.txt"
# Windows' own line ends for the text files people open.
sed -i 's/$/\r/' "$STAGE/README.txt" "$STAGE/LICENSE.txt"

step "OpenDMTQ.exe"
# The version in the file's details: four numbers (a release's, or the date's) and the text.
# Without leading zeros: the resource compiler reads 08 as a broken octal number.
numbers=$(echo "$VERSION" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' | awk -F. '{printf "%d,%d,%d", $1, $2, $3}' || true)
numbers=${numbers:-0,0,0},0
work=$(mktemp -d)
cp /build/launcher.c /build/launcher.rc /build/opendmtq.ico "$work/"
x86_64-w64-mingw32-windres -DOPENDMTQ_VERSION_NUMBERS="$numbers" -DOPENDMTQ_VERSION_TEXT="\\\"$VERSION\\\"" \
  -I "$work" "$work/launcher.rc" -O coff -o "$work/launcher.res"
# Linked statically: it needs no MinGW DLL on the PC, only Windows' own.
x86_64-w64-mingw32-gcc -O2 -Wall -Wextra -municode -static -s -o "$STAGE/OpenDMTQ.exe" "$work/launcher.c" "$work/launcher.res"
rm -rf "$work"

step "Notices"
python3 - "$STAGE" "$VERSION" <<PY
import pathlib, sys
stage = pathlib.Path(sys.argv[1])
libs = sorted(p.name.rsplit("-", 1)[0].replace("_", "-") + " " + p.name.rsplit("-", 1)[1].removesuffix(".dist-info")
              for p in (stage / "runtime/python/Lib/site-packages").glob("*.dist-info"))
rows = [
    ("Apache HTTP Server $APACHE_VERSION (Apache Lounge build)", "Apache License 2.0", "runtime/apache/LICENSE.txt, NOTICE.txt"),
    ("PHP $PHP_VERSION", "PHP License 3.01", "runtime/php/license.txt"),
    ("Python $PYTHON_VERSION, with the Microsoft C runtime it ships", "PSF License Agreement", "runtime/python/LICENSE.txt"),
    ("Eclipse Temurin $JRE_VERSION (Java)", "GPL v2 with the Classpath Exception; source: https://github.com/adoptium/jdk21u",
     "runtime/java/legal/"),
    ("7-Zip $SEVENZIP_VERSION", "GNU LGPL, BSD 3-clause, unRAR restriction", "runtime/7zip/License.txt"),
    ("Apktool 2.12.1", "Apache License 2.0", "runtime/apache/LICENSE.txt (the same text); https://github.com/iBotPeaches/Apktool"),
    ("uber-apk-signer 1.3.0", "Apache License 2.0", "runtime/apache/LICENSE.txt (the same text); https://github.com/patrickfav/uber-apk-signer"),
    ("Python libraries: " + ", ".join(libs), "BSD, MIT, PSF, HPND and ZPL licenses", "runtime/python/Lib/site-packages/*.dist-info/"),
    ("Saira and Pretendard fonts, cut down", "SIL Open Font License 1.1", "app/server/portal/fonts/"),
    ("hls.js", "Apache License 2.0", "app/server/portal/hls/LICENSE"),
    ("The arm32 runtime: Dynarmic with OpenDMTQ's changes and the libraries it brings, and Android's 32-bit linker and system libraries, unchanged",
     "0BSD, MIT, Apache License 2.0, BSD, ISC, zlib and NCSA licenses",
     "notices/ in app/tools/opendmtq_tools/opendmtq-arm32-runtime.zip"),
    ("The installer for Windows that the site hands players: the PC client (Python, Tk, Velopack) and the player (the arm32 "
     "runtime above, ANGLE, zlib, the GCC runtime and winpthreads)",
     "MIT, PSF, BSD, 0BSD, zlib, GPL 3 with the GCC Runtime Library Exception, Apache License 2.0 with LLVM Exceptions",
     "the licenses folder of the program it installs (app/tools/opendmtq_tools/OpenDMTQ-Setup.exe)"),
]
text = ["OpenDMTQ for Windows brings these programs and parts, unchanged, each under its own license. The full texts",
        "are in the folders named. OpenDMTQ's own code is under the MIT License (LICENSE.txt).", ""]
for name, licence, where in rows:
    text += [name, "  License: " + licence, "  Text:    " + where, ""]
(stage / "THIRD-PARTY-NOTICES.txt").write_text("\r\n".join(text), encoding="utf-8")
print(len(rows), "entries")
PY

step "Every program finds its DLLs"
# Windows' own DLLs (and the API sets of its C runtime), which every supported Windows has.
python3 - "$STAGE" <<'PY'
import pathlib, re, subprocess, sys
stage = pathlib.Path(sys.argv[1])
system = {d.lower() for d in """kernel32.dll advapi32.dll user32.dll shell32.dll ole32.dll oleaut32.dll ws2_32.dll crypt32.dll
    dnsapi.dll iphlpapi.dll bcrypt.dll rpcrt4.dll secur32.dll shlwapi.dll version.dll winmm.dll gdi32.dll comdlg32.dll
    comctl32.dll mswsock.dll userenv.dll ntdll.dll psapi.dll setupapi.dll wldap32.dll normaliz.dll netapi32.dll
    imm32.dll uxtheme.dll dbghelp.dll wintrust.dll cfgmgr32.dll bcryptprimitives.dll ncrypt.dll msvcrt.dll odbc32.dll
    cabinet.dll msi.dll propsys.dll""".split()}
# Each program and the folders Windows looks in for it: its own, and the PATH the host program gives Apache and PHP.
rt = stage / "runtime"
extra = [rt / "php", rt / "apache" / "bin", rt / "python"]
problems, checked = [], 0
for top in (stage, rt / "apache", rt / "php", rt / "python"):
    for f in sorted(top.rglob("*")) if top != stage else [stage / "OpenDMTQ.exe"]:
        if f.suffix.lower() not in (".exe", ".dll", ".so", ".pyd"):
            continue
        out = subprocess.run(["x86_64-w64-mingw32-objdump", "-p", str(f)], capture_output=True, text=True).stdout
        for dll in sorted({m.lower() for m in re.findall(r"DLL Name: (\S+)", out)}):
            if dll in system or dll.startswith("api-ms-win-") or dll.startswith("ext-ms-"):
                continue
            if any((d / dll).exists() or any(p.name.lower() == dll for p in d.iterdir()) for d in [f.parent] + extra):
                continue
            problems.append(f"{f.relative_to(stage)} needs {dll}, which is not in the bundle")
        checked += 1
for p in problems:
    print("error:", p)
print(f"{checked} programs and libraries checked, {len(problems)} missing DLLs")
sys.exit(1 if problems else 0)
PY

step "The zip"
rm -f "$OUT/OpenDMTQ-windows.zip"
(cd "$OUT" && zip -q -r -9 OpenDMTQ-windows.zip OpenDMTQ)
(cd "$OUT" && sha256sum OpenDMTQ-windows.zip > OpenDMTQ-windows.zip.sha256)
rm -rf "$OUT/unpack"
du -sh "$STAGE" "$OUT/OpenDMTQ-windows.zip"
