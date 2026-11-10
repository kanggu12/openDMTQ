#!/bin/sh
# Runs the guest test programs of arm32/test.sh with the Windows build of the runner (arm32/build_windows.sh), under
# Wine in a container: the same programs and the same checks as on a phone and on a desktop Linux host, on the runtime's
# Windows layer (arm32/src/win). Then the tests of the desktop player's parts that arm32/test_desktop.sh runs on Linux:
# the Java VM, the mixer, and the video reader with Windows' own decoders (Media Foundation); and the broadcast's requests
# that CI tests on Linux, on the layer's sockets, which are the player's own. The Wine image is arm32/wine.Dockerfile's.
#
#   arm32/test_windows.sh
#
# The guest programs and the guest's system libraries come from the Android build (arm32/build.sh) in _work/arm32; the
# Windows programs from arm32/build_windows.sh arm32run jvmtest audiotest mediatest settingstest livenettest.
set -eu
# The repository, wherever this script is called from.
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
# Both builds must be there: the Windows programs, and the guest programs the runner runs.
for exe in arm32run jvmtest audiotest mediatest settingstest livenettest; do
  [ -f "$root/_work/arm32/build-windows-x86_64/$exe.exe" ] || { echo "no $exe.exe: run arm32/build_windows.sh arm32run jvmtest audiotest mediatest settingstest livenettest" >&2; exit 1; }
done
[ -f "$root/_work/arm32/guest/basic" ] || { echo "no guest programs: run arm32/build.sh" >&2; exit 1; }
# The test image, made again only when its file changed (Docker's cache).
docker build -q -t opendmtq-arm32-wine -f "$here/wine.Dockerfile" "$here" >/dev/null
# A time zone for the host, which the runtime gives the guest as a phone gives its own (the zones test reads it back);
# no network. The programs run from a folder of their own, which the memory test writes a file in.
docker run --rm --network none -e TZ=Asia/Seoul -e WINEDEBUG=-all -e WINEPREFIX=/tmp/wine -v "$root:/r:ro" -w /tmp opendmtq-arm32-wine sh -c '
wineboot -i >/dev/null 2>&1
w=/r/_work/arm32
b=$w/build-windows-x86_64
run="wine $b/arm32run.exe"
failed=0
# Each program prints ALL CHECKS PASSED when every check held. The signal, interrupt and wake tests run several times:
# thread handshakes are where timing bugs show.
for test in basic signals signals signals signals signals interrupt interrupt interrupt wakes wakes wakes restart restart \
    coherence cxx neon memory calls descriptors zones "dl $w/guest/libplugin.so"; do
  set -- $test
  out=$(timeout 300 $run --sysroot $w/sysroot $w/guest/$1 ${2:-} 2>&1 || true)
  if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS $1"
  else echo "FAIL $1"; echo "$out" | grep -v "DT_FLAGS_1" | tail -n 15 | sed "s/^/    /"; failed=1
  fi
done
# With fastmem, a store into a PROT_NONE page (a thread stack guard) must still fault: the runtime ends the process
# there, so the line after the store never prints.
out=$(timeout 120 $run --sysroot $w/sysroot --fastmem $w/guest/guard 2>&1 || true)
if echo "$out" | grep -q "touching a PROT_NONE page" && ! echo "$out" | grep -q "did not fault"; then echo "PASS guard"
else echo "FAIL guard"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# The bridge: four host threads become guest threads and call into a guest library.
out=$(timeout 120 $run --sysroot $w/sysroot --agent $w/guest/arm32-agent --call $w/guest/libplugin.so plugin_add --threads 4 2 3 2>&1 || true)
if [ "$(echo "$out" | grep -c "returned 1005")" = 4 ]; then echo "PASS bridge"
else echo "FAIL bridge"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# Eight host threads become guest threads 5 ms apart while the running ones create and join guest threads.
out=$(timeout 120 $run --sysroot $w/sysroot --agent $w/guest/arm32-agent --call $w/guest/libplugin.so plugin_spawn --threads 8 --stagger 5 100 2>&1 || true)
if [ "$(echo "$out" | grep -c "returned 100$")" = 8 ]; then echo "PASS bridge-spawn"
else echo "FAIL bridge-spawn"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# The Java VM the desktop player hosts the game in (arm32/jvm/test.cpp), with its count of checks. The C runtime of
# Windows ends the lines of these programs with CR LF: the CRs go.
out=$(timeout 300 wine $b/jvmtest.exe 2>&1 | tr -d "\r" || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS jvm ($(echo "$out" | grep " checks$"))"
else echo "FAIL jvm"; echo "$out" | grep -v "called (no body)" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The mixer of the desktop player: its resampler, streams and outputs (arm32/desktop/audiotest.cpp).
out=$(timeout 300 wine $b/audiotest.exe 2>&1 | tr -d "\r" || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS audio ($(echo "$out" | grep " checks$"))"
else echo "FAIL audio"; echo "$out" | grep -v "^ok" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The PC settings file of the desktop player, as the PC client writes it (arm32/desktop/settingstest.cpp), from /tmp, where it
# may write its file.
out=$(timeout 120 wine $b/settingstest.exe 2>&1 | tr -d "\r" || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS settings ($(echo "$out" | grep " checks$"))"
else echo "FAIL settings"; echo "$out" | grep -v "^player: settings" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The broadcast requests to the server (arm32/tests/host/live_net_test.cpp, which CI runs on Linux), here through the
# Windows layer of the runtime, whose sockets the player uses too: against stand-in servers on 127.0.0.1 (the loopback of
# the container, all it has), each request within its deadline, the answers read as meant, the upload queue and its steps.
out=$(timeout 300 wine $b/livenettest.exe 2>&1 | tr -d "\r" || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS live-net ($(echo "$out" | grep " checks$"))"
else echo "FAIL live-net"; echo "$out" | grep -v "^ok" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The video path of the desktop player with Media Foundation decoding, on a file made here by FFmpeg (a red picture,
# a tone): the same file and checks as on Linux.
ffmpeg -loglevel error -y -f lavfi -i color=c=red:s=320x240:r=30 -f lavfi -i sine=frequency=1000:sample_rate=48000 -t 2 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ac 2 -shortest /tmp/media-test.mp4
out=$(timeout 300 wine $b/mediatest.exe /tmp/media-test.mp4 2>&1 | tr -d "\r" || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS media ($(echo "$out" | grep " checks$"))"
else echo "FAIL media"; echo "$out" | grep -v "^ok" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# One line for scripts to read.
if [ $failed = 0 ]; then echo "ALL GUEST TESTS PASSED ON WINDOWS (WINE)"; else echo "SOME GUEST TESTS FAILED"; exit 1; fi
'
