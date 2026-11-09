#!/bin/sh
# Runs the guest test programs of arm32/test.sh with the desktop build of the runner (arm32/build_desktop.sh), in its
# container: the same programs and the same checks, with no phone or emulator; then the tests of the Java VM that stands
# in for Android's on a desktop host (arm32/jvm), and of the desktop player's mixer. The JNI test needs Android's ART
# and stays in arm32/test.sh.
#
#   arm32/test_desktop.sh
#
# The guest programs and the guest's system libraries come from the Android build (arm32/build.sh) in _work/arm32.
set -eu
# The repository, wherever this script is called from.
here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")
# Both builds must be there: the runner, and the guest programs it runs.
[ -x "$root/_work/arm32/build-desktop-x86_64/arm32run" ] || { echo "no desktop runner: run arm32/build_desktop.sh" >&2; exit 1; }
[ -f "$root/_work/arm32/guest/basic" ] || { echo "no guest programs: run arm32/build.sh" >&2; exit 1; }
# A time zone for the host, which the runtime gives the guest as a phone gives its own (the zones test reads it back).
docker run --rm -e TZ=Asia/Seoul -v "$root:/r" -w /r opendmtq-arm32-desktop sh -c '
w=/r/_work/arm32
run=$w/build-desktop-x86_64/arm32run
failed=0
# Each program prints ALL CHECKS PASSED when every check held. The signal, interrupt and wake tests run several times:
# thread handshakes are where timing bugs show.
for test in basic signals signals signals signals signals interrupt interrupt interrupt wakes wakes wakes restart restart \
    coherence cxx neon memory calls descriptors zones "dl $w/guest/libplugin.so"; do
  set -- $test
  out=$($run --sysroot $w/sysroot $w/guest/$1 ${2:-} 2>&1 || true)
  if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS $1"
  else echo "FAIL $1"; echo "$out" | tail -n 15 | sed "s/^/    /"; failed=1
  fi
done
# With fastmem, a store into a PROT_NONE page (a thread stack guard) must still fault: the runtime ends the process
# there, so the line after the store never prints.
out=$($run --sysroot $w/sysroot --fastmem $w/guest/guard 2>&1 || true)
if echo "$out" | grep -q "touching a PROT_NONE page" && ! echo "$out" | grep -q "did not fault"; then echo "PASS guard"
else echo "FAIL guard"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# The bridge: four host threads become guest threads and call into a guest library.
out=$($run --sysroot $w/sysroot --agent $w/guest/arm32-agent --call $w/guest/libplugin.so plugin_add --threads 4 2 3 2>&1 || true)
if [ "$(echo "$out" | grep -c "returned 1005")" = 4 ]; then echo "PASS bridge"
else echo "FAIL bridge"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# Eight host threads become guest threads 5 ms apart while the running ones create and join guest threads.
out=$($run --sysroot $w/sysroot --agent $w/guest/arm32-agent --call $w/guest/libplugin.so plugin_spawn --threads 8 --stagger 5 100 2>&1 || true)
if [ "$(echo "$out" | grep -c "returned 100$")" = 8 ]; then echo "PASS bridge-spawn"
else echo "FAIL bridge-spawn"; echo "$out" | tail -n 10 | sed "s/^/    /"; failed=1
fi
# The Java VM of arm32/jvm through JNI, as native code uses it.
out=$(_work/arm32/build-desktop-x86_64/jvmtest 2>&1 || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS jvm ($(echo "$out" | grep -c "^" ) lines, $(echo "$out" | grep " checks$"))"
else echo "FAIL jvm"; echo "$out" | grep -v "called (no body)" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The mixer of the desktop player: its resampler, streams and outputs (arm32/desktop/audiotest.cpp).
out=$(_work/arm32/build-desktop-x86_64/audiotest 2>&1 || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS audio ($(echo "$out" | grep " checks$"))"
else echo "FAIL audio"; echo "$out" | grep -v "^ok" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The PC settings file of the desktop player, as the PC client writes it (arm32/desktop/settingstest.cpp), in a folder it may
# write its file in.
out=$(cd /tmp && /r/_work/arm32/build-desktop-x86_64/settingstest 2>&1 || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS settings ($(echo "$out" | grep " checks$"))"
else echo "FAIL settings"; echo "$out" | grep -v "^player: settings" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# The video path of the desktop player: its MP4 reader and decoders, on a file made here by FFmpeg (a red picture, a tone).
ffmpeg -loglevel error -y -f lavfi -i color=c=red:s=320x240:r=30 -f lavfi -i sine=frequency=1000:sample_rate=48000 -t 2 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ac 2 -shortest /tmp/media-test.mp4
out=$(_work/arm32/build-desktop-x86_64/mediatest /tmp/media-test.mp4 2>&1 || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then echo "PASS media ($(echo "$out" | grep " checks$"))"
else echo "FAIL media"; echo "$out" | grep -v "^ok" | tail -n 15 | sed "s/^/    /"; failed=1
fi
# One line for scripts to read.
if [ $failed = 0 ]; then echo "ALL GUEST TESTS PASSED ON THE DESKTOP HOST"; else echo "SOME GUEST TESTS FAILED"; exit 1; fi
'
