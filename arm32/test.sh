#!/bin/sh
# Runs the guest test programs through the runner on a device or emulator over adb.
#
#   arm32/test.sh [adb serial]
#
# Build first with arm32/build.sh for the device's ABI.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
work=$(dirname "$here")/_work/arm32
adb=${ADB:-adb}
[ $# -gt 0 ] && adb="$adb -s $1"
dir=/data/local/tmp/arm32
abi=$($adb shell getprop ro.product.cpu.abi | tr -d '\r')
runner=$work/build-$abi/arm32run
[ -f "$runner" ] || { echo "no runner for $abi; run arm32/build.sh $abi" >&2; exit 1; }
$adb shell "mkdir -p $dir/sysroot"
$adb push -q "$work/sysroot/." "$dir/sysroot/"
$adb push -q "$runner" "$dir/arm32run"
$adb push -q "$work/guest/." "$dir/"
$adb shell "chmod 755 $dir/arm32run"
failed=0
# The signal tests run several times: thread handshakes are where timing bugs show.
for test in basic signals signals signals signals signals interrupt interrupt interrupt wakes wakes wakes futexes restart restart \
    coherence cxx neon memory calls descriptors zones "dl $dir/libplugin.so"; do
    out=$($adb shell "cd $dir && ./arm32run --sysroot $dir/sysroot $dir/$test 2>&1" | tr -d '\r' || true)
    if echo "$out" | grep -q "ALL CHECKS PASSED"; then
        echo "PASS ${test%% *}"
    else
        echo "FAIL ${test%% *}"
        echo "$out" | sed 's/^/    /'
        failed=1
    fi
done
# With fastmem, a store into a PROT_NONE page (a thread's stack guard) must still fault: the
# runtime ends the process there, so the line after the store never prints.
out=$($adb shell "cd $dir && ./arm32run --sysroot $dir/sysroot --fastmem $dir/guard 2>&1" | tr -d '\r' || true)
if echo "$out" | grep -q "touching a PROT_NONE page" && ! echo "$out" | grep -q "did not fault"; then
    echo "PASS guard"
else
    echo "FAIL guard"
    echo "$out" | sed 's/^/    /'
    failed=1
fi
# The app bridge: four host threads become guest threads and call into a guest library.
out=$($adb shell "cd $dir && ./arm32run --sysroot $dir/sysroot --agent $dir/arm32-agent --call $dir/libplugin.so plugin_add --threads 4 2 3 2>&1" | tr -d '\r' || true)
if [ "$(echo "$out" | grep -c 'returned 1005')" = 4 ]; then
    echo "PASS bridge"
else
    echo "FAIL bridge"
    echo "$out" | sed 's/^/    /'
    failed=1
fi
# Eight host threads become guest threads, 5 ms apart, while the ones already running create and
# join guest threads: every clone must run its own start routine, none may land on a host thread
# that waits for a guest thread. Each guest thread ends with its host thread.
out=$($adb shell "cd $dir && ./arm32run --sysroot $dir/sysroot --agent $dir/arm32-agent --call $dir/libplugin.so plugin_spawn --threads 8 --stagger 5 100 2>&1" | tr -d '\r' || true)
if [ "$(echo "$out" | grep -c 'returned 100$')" = 8 ]; then
    echo "PASS bridge-spawn"
else
    echo "FAIL bridge-spawn"
    echo "$out" | sed 's/^/    /'
    failed=1
fi
# JNI in ART: an app-style library folder (runtime, proxy, guest files under their prefixes) and
# a Java test run with app_process.
app=$dir/app
$adb shell "rm -rf $app && mkdir -p $app"
$adb push -q "$work/build-$abi/libarm32.so" "$app/libarm32.so"
$adb push -q "$work/build-$abi/libarm32proxy.so" "$app/libjnitest.so"
$adb push -q "$work/sysroot/bin/linker" "$app/libarm32s-linker.so"
for f in "$work"/sysroot/lib/*.so; do $adb push -q "$f" "$app/libarm32s-$(basename "$f")"; done
$adb push -q "$work/guest/arm32-agent" "$app/libarm32s-arm32-agent.so"
$adb push -q "$work/guest/libarm32g-libjnitest.so" "$app/"
$adb push -q "$work/guest/libplugin.so" "$app/libarm32g-libplugin.so"
$adb push -q "$work/guest/jnitest.dex" "$app/test.dex"
out=$($adb shell "app_process -cp $app/test.dex /system/bin Arm32JniTest $app 2>&1" | tr -d '\r' || true)
if echo "$out" | grep -q "ALL CHECKS PASSED"; then
    echo "PASS jni"
else
    echo "FAIL jni"
    echo "$out" | sed 's/^/    /'
    failed=1
fi
exit $failed
