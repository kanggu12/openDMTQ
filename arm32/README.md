# arm32

Runs 32-bit ARM Android code on 64-bit-only phones.

The game client contains only 32-bit ARM code (Unity 5.6, IL2CPP), and newer phones (Pixel 7 and later, Galaxy S24
and later, and others whose chips dropped 32-bit support) cannot execute it. There is no 64-bit build of
the game and no source to make one. This runtime runs the original 32-bit code unchanged, in a 64-bit app that
carries it and the game's own libraries. A release hands it out ready-made and the server's app builder adds it by itself
(`tools/opendmtq_tools/runtime.py`). `arm32/bundle.sh`, or with Docker Compose `./opendmtq runtime --build`, makes it from this
source.

## How it works

The guest is an ordinary 32-bit ARM Linux process as far as its code can tell, emulated inside a
64-bit process:

- **CPU:** [Dynarmic](https://github.com/azahar-emu/dynarmic) translates ARM and Thumb code (with
  VFP and NEON) to the host's instructions, one JIT per guest thread.
- **Memory:** a 4 GB block of host address space, guest address `g` at host `base + g`. Guest pages
  are 4 KB whatever the host's page size; protections live in the mapping list and the JIT's page
  table. With fastmem, host pages whose guest pages are all `PROT_NONE` are closed on the host as
  well, so stack guard pages still fault. mmap places nothing below 128 MB unless asked for that
  address: smaller values passed to GL are buffer offsets.
- **System libraries:** the real 32-bit Android dynamic linker and C library from the AOSP Android
  6.0 image. The guest's linker loads libraries, resolves symbols and runs constructors.
- **System calls:** the ARM EABI calls are carried out by the host kernel. Arguments are converted
  where the 32-bit layout differs (`stat64`, `timespec`, `iovec`, `sigaction`, `epoll_event`, open
  flags, `select`, the old `stat` and 32-bit `struct flock`). Guest threads are host threads.
  `/proc/self/maps` and `/proc/cpuinfo` describe the guest, and the guest's C library gets a
  property area of its own (the host's, split per SELinux context since Android 7, is one it cannot
  read): the ARMv7 ABI and the host's build, model and time zone values.
- **Signals:** sent between guest threads and delivered with Linux's ARM signal frame, including
  `rt_sigsuspend`, which the IL2CPP garbage collector uses to stop threads.

## Status

Command-line programs run: `arm32run` starts a 32-bit executable with its linker. The tests cover
C library start-up, heap, time, files, threads, signals between threads, C++ exceptions and RTTI,
NEON and VFP arithmetic, and `dlopen`.

On a Galaxy S26 Ultra (64-bit only, Android 17) all tests pass, the signal test 40 times in a
row. Speed against the same code built for 64-bit, on the fastest core, best of five
(`tests/bench.c`): integer work 3x slower, memory copies 1.6x, a scalar float loop 4.3x.

The float loop was 11.6x until Dynarmic stopped reading and clearing the host FPSR around every
translated block (`patches/dynarmic-ignore-fpsr.patch`, on by default): results are identical,
only the FPSCR sticky exception flags, which Android code does not read, are no longer
collected (`--fp-flags` brings them back). `--fast-fp` (inexact NaN and FPSCR corner cases) and
`--fastmem` (no page table lookup) made no further difference. `ARM32_TRACE=1` logs signal
traffic.

Inside an app (in ART, through `app_process`) the JNI bridge passes its test on the emulator and the
S26: native methods registered by 32-bit code with ten mixed arguments, arrays, strings, fields,
calls back into Java in all three argument forms, direct buffers both ways, exceptions,
references, and 32-bit threads attaching to the VM.

The system API bridges pass on both as well: 32-bit code draws through EGL and OpenGL ES on the
host GPU (a pbuffer: clear, shaders built from several strings, buffer offsets and client arrays,
a mapped buffer, eglGetProcAddress) and plays through an OpenSL ES buffer queue whose callbacks
arrive on the host's audio thread. The GL bridge is generated from the NDK headers (852
functions, `tools/gen_gl.py`); EGL, libandroid and OpenSL ES are written by hand, with their
guest stub libraries generated from `guest/*.list` (`tools/gen_stubs.py`).

The game runs. The server's APK builder adds the runtime to the game (see below), and on the
x86_64 emulator the game goes through the whole flow on the runtime:
start-up, login, the song list, a song played to the end with its video background and audio
output running, and the result the server records (the notice web view also ran, before the
patcher started skipping it). The pieces that took (all covered by the tests):

- **Signals for threads that are in Java.** The IL2CPP garbage collector stops the world by
  signalling every thread it knows and waiting for each to answer from its handler. A Java thread
  that once called into the game sits in Java between calls, where no guest code runs; a helper
  host thread runs the handler on that thread's guest state instead, the way the kernel would
  interrupt whatever the thread was doing. Host threads hold a thread's guest context while they
  run its code and give it back during JNI calls into Java, which may take long.
- **Native methods found by name.** Libraries that export `Java_<class>_<method>` instead of
  registering their methods are bound at load time: their exports are read from the ELF file and
  registered with the signatures reflection reports, overloads included.
- **Direct buffers.** A Java buffer outside guest memory is copied in when guest code asks for
  its address and written back when that native call returns, only the blocks the guest changed
  and never for read-only buffers: a video decoder's buffer may be released during the call. A
  view's capacity counts its elements (four bytes for a `FloatBuffer`), and a thread's copies are
  freed when it ends (Unity's web requests run a thread each, with a 128 KB buffer of their own).
- **NEON.** Dynarmic leaves eight ARMv7 SIMD instructions out (`VADDHN`, `VRADDHN`, `VSUBHN`,
  `VRSUBHN`, `VQDMULL`, `VQDMLAL`/`VQDMLSL` in both forms, `VQRSHL`); the game's video code uses
  them. `patches/dynarmic-asimd-missing.patch` adds them, checked against C in `tests/neon.c`.
- **Hang dump.** With tracing or stats on, when the app presents no frame for eight seconds, every guest
  thread is logged: the system call or host function it is in, its registers, and the code
  addresses on its stack as `library+offset`.

## In the server's APK

```sh
arm32/bundle.sh      # builds the runtime if needed and puts it in data/apk/arm32
./opendmtq up        # the builder repacks the app with it
```

The builder (`tools/opendmtq_tools/pack_arm64.py`) keeps the game's `lib/armeabi-v7a` and adds
`lib/arm64-v8a` with the runtime, a proxy under each 32-bit library's name, the 32-bit libraries
as `libarm32g-<name>` and the guest system as `libarm32s-<name>`. The manifest gets `multiArch`
and `use32bitAbi`, so one APK serves every phone: Android 7 and later install it as a 32-bit app
where 32-bit apps run (the game runs natively, as before), and phones without 32-bit support
only match `lib/arm64-v8a`. (64-bit phones on Android 5 and 6 do not know `use32bitAbi` and take
the runtime too; it is built for API 21 so that it loads there.)

`pack_arm64 --only-64bit --abi x86_64` with a bundle that has the x86_64 build makes an APK that
runs the game through the runtime on the x86_64 emulator. In the app, `setprop debug.arm32.trace
1` logs signal traffic and hang dumps, `debug.arm32.stats 1` frames per second, per-thread CPU
and call counts, frame-interval percentiles and garbage collector pauses every five seconds,
`debug.arm32.fastmem 0` turns fastmem off (on by default: a fifth less CPU on the game's main
thread) and `debug.arm32.fastneon 0` fast NEON (on by default). Dynarmic's arm64 backend
switched the host FPCR to the ASIMD standard value and back around every NEON float
instruction; `patches/dynarmic-arm64-ignore-standard-fpcr.patch` lets the unsafe option skip
that, which made a NEON multiply-add loop twelve times faster on a Galaxy S26 Ultra (only
denormals and NaN payloads can differ). The app libraries are linked with 16 KB segment
alignment for phones with 16 KB pages.

Two more defaults aim at even frame pacing. `debug.arm32.fastatomics` (on): exclusive loads and
stores without Dynarmic's monitor lock, which every thread's atomics shared; the store is a
compare-and-swap against the value the load saw, as in QEMU's user mode
(`patches/dynarmic-arm64-lockfree-exclusive.patch`; the x86-64 backend has this built in). With
the lock, four threads incrementing one counter took 2.9 s and up to 4.1 ms for a single
increment on the emulator; without it 0.25 s and 0.6 ms. `debug.arm32.framerate` (unset: follow
the display, see Frame rate): the frame rate, which the game's window also asks the display for,
so each frame gets exactly one refresh instead of alternating two and three (a 60 fps game on a
120 Hz panel); 0 asks for nothing and leaves the game its own cap.

**Frame pacing** (`src/pacing.cpp`, `debug.arm32.pacing`, on). A game that holds its frame rate
with a timer, as Unity's `targetFrameRate` does, runs out of step with a display that refreshes
several times per frame: on a 120 Hz panel a 60 fps frame stays for two refreshes or three. When
the display stays at a whole multiple of the frame rate, the runtime paces the swaps instead, the
way Android's frame pacing library (Swappy) does. From the compositor's timing
(`EGL_ANDROID_get_frame_timestamps`) it asks each frame to be shown a whole number of refreshes
after the one before (`EGL_ANDROID_presentation_time`), and after the swap it holds the thread
until shortly before that frame's composition deadline, so the next frame starts with its full
time ahead and never waits in the queue. Meanwhile the game's own cap is set to twice the frame
rate so it never holds a frame back. The swap runs detached from the guest, so collector signals
are not delayed by the wait. On Android 13 and later each frame's work time also goes to the
performance hint API (ADPF, `debug.arm32.adpf`, on), so the CPU clock rises before frames run late.
For an unpaced frame that is the time between its swaps less what the thread slept in nanosleep,
the game's own limiter (6.9 ms of 8.3 at 120 fps on a Galaxy S26 Ultra). There the hints made no
measured difference: no frame was late with or without them. With one refresh per frame (the display switched to the frame rate) nothing is paced, as
there is nothing to even out: on a Galaxy S26 Ultra the game's own limiter kept 99.8 % of the
frames one refresh apart, at 60 Hz and at 120 Hz. Unpaced frames then go back to the automatic
presentation time, which otherwise stays on the window: the compositor drops a frame with a time of
its own when a newer one is due too, and after the S26's adaptive panel went to 120 Hz for a second
(paced meanwhile) 6 to 7 % of the frames never reached the screen. Swaps use interval 1 only while
pacing; otherwise the game's own stands (Technika Q asks for 1). With stats on, a line reports the
intervals at which frames reached the screen and how many came later than asked.

**Frame rate** (`src/follow.cpp`, fed by `src/pacing.cpp`; `debug.arm32.framerate` unset). The frame rate follows the
display, once the cap tweak has found its field and the game's target can be read (until then it
is 60, and the window asks for 60 Hz). The game's window, the one its EGL surface draws on, asks
for 144 Hz, the most there is any use for, and the panel answers with the nearest it has: once that has
held for a second (five for a rate outside the usual 144, 120, 90, 72 and 60) it becomes the frame rate
and the game's cap follows it (Tweaks), so each frame gets one refresh. Above 60 fps the pace is checked
every two seconds while the game aims that high (an edit to the game keeps untouched menus from stepping down to 18 fps
for its old battery saving, `SetTargetFrameRate`; its target still changes between scenes), so the runtime reads
`Application.targetFrameRate` every tenth frame through the il2cpp API and drops a window in which it changed. The check goes by what the screen showed (the
frames' present times): a phone's window falls short when more than 3 % of the frames stayed on screen for more
than one refresh. With each frame stretched by 6 ms a Galaxy S26 Ultra made 110 fps and 7 % of its frames
did; at full speed 0.1 %. The gaps between swaps are no guide: there a fifth of them were half a refresh
off while every frame still got its own refresh. A phone without present times is judged by the rate
frames came at (under 97 % falls short). Three short windows without a good one between take one step
down the list for the rest of the run: the window asks for that rate, and the frame rate is the panel's
refresh rate or the highest whole fraction of it not above that (72 fps on a panel that stays at 144 Hz, and
those are paced). The phone's own word that it is hot (thermal status SEVERE or worse) takes a step
too, every half minute while it lasts. `tests/host/follow_test.cpp` plays these on the build machine, with a
display and a game of its own: a phone's 120 Hz panel down to 90, 72 and 60, one that stays at 120 Hz, the heat's
steps, and a computer's display (below).

On a computer the display keeps its own rate whatever a window asks, and its compositor gives no frame
times. The player reads the rate of the display its window is on and that display's refreshes from the
system (the display configuration and DXGI on Windows) and hands them to the runtime (`g_display_interval`,
`g_display_vblank`). The frame rate starts at every refresh, whatever the rate (240 Hz, 180 Hz, 59.94 Hz),
and the steps down are every second refresh, every third, while that stays at 57 fps or more. Each frame
goes out on its refresh: the swap interval holds it for its share, and after the swap the thread waits for
the refresh the frame goes on screen at, so that no frame waits in the swap queue. The pace check counts the
frames that missed their refresh, and a computer's window falls short when more than a quarter of its frames did
(a phone's at 3 %, above): three short windows of 2 s in a row take a step down. 5 s after a step down the faster
rate is tried again (a song's load holds the frames up for some seconds, after which every refresh holds again); a
try that falls short in its first two windows goes back down at once and doubles the wait, up to a minute: a step
on a computer's display shows nothing, where a phone's panel switch can. A computer keeps its resolution, which the
render scale of the PC client's settings chooses.

The PC client's settings can set a frame limit and turn VSync off: the player reads them from the file the client
writes (`desktop/settings.cpp`) and hands them to the runtime (`g_host_fps_cap`, `g_host_vsync`). With VSync on, a limit
keeps every frame on the fewest refreshes that hold the rate at or under it, when that rate is at most 10 % under the
limit and a frame needs no more than four refreshes (`src/pacing_math.h`, which `tests/host/pacing_math_test.cpp` checks
on the build machine): 120 on a 240 Hz display is every second refresh. Any other limit, such as 144 on 240 Hz, goes by
the clock, each frame still waiting for a refresh. A step back up never passes the limit. With VSync off the swap
interval is 0 whatever the game asks, and the frames go out by the clock at the limit: the display's rate, the number
chosen, or 1000 a second for No limit. By the clock, each frame goes one frame's time after the one before, however
unevenly the game's own limiter hands them over; a frame later than that by more than a frame's time starts the count
again from itself, so that no burst follows a load (`clock_due`, checked by the same test).

**Resolution** (`src/pacing.cpp`, `debug.arm32.lowres`, unset). The game draws at the panel's own resolution (an edit to the game:
it used to write its low resolution option on at every start, 960 lines on a 1440 line panel), in 32-bit colour and with its
textures at full size. With all that a Galaxy S26 Ultra keeps 120 fps with no frame late in a song. Frames come before sharpness, so
a device that falls short (the check above, here also at 60 fps) gets the game's own low resolution from the next start on, through
`LowResolution.Apply(true)` a few seconds in: a mark in the app's files says so. Not at once, because a song that has begun goes by
the resolution it started with; until the next start the frame rate gives way as above.

The JIT treats code pages from files (read-only, executable) as constant: a load from a fixed
address there, as ARM code does for its literal pools, is folded into the translated code. Such
pages are remembered, and a later change to one of them (code patched in place and flushed) clears
every thread's translated code, not just the range.

**Tweaks.** The packer can install a text file next to the runtime (`libarm32t-tweaks.so`) that
sets static int fields of IL2CPP classes, through the il2cpp API on Unity's main thread, once the
class is initialised (`src/tweaks.cpp`). OpenDMTQ uses it to raise Technika Q's frame cap
(`VariableFrameController.maxFpsVal` and `maxOutgameFpsVal`, 60 in the game) to the app frame
rate (twice that while frames are paced). Of the game's code only NGUI reads `Time.frameCount`, to
update once per frame; the chart runs on a millisecond timer, and a song took the same time at 40
and 60 fps.

**Live view** (`src/live.cpp`, `src/live_ts.cpp`, `debug.arm32.live`, on; see
[docs/live.md](../docs/live.md)). Off for a player until the server's owner turns it on. The control
thread asks `GET /live/state` every 15 seconds while the game is on screen, with the device ids the
platform SDK signed in with: it reads them from `PPDevice`'s static fields and never calls the getters,
which remember their first answer. With live view off, the swap costs one atomic load and each audio
buffer another.

With it on, a picture is due at the stream's frame rate (every fourth swap of a game at 120 fps for a stream at
30, every second for one at 60): that swap scales the frame into a texture with one GPU blit and leaves a
fence behind it. An encoder thread with its own EGL context, sharing that texture, draws it on the
input surface of the hardware H.264 encoder, so no pixel passes through the CPU. The game has two FMOD
outputs (48 and 44.1 kHz), so the sound of each OpenSL buffer queue goes through a ring of its own into
a mix at 48 kHz, made by the clock so that a source that stops leaves silence, not a gap, and into the
hardware AAC encoder. Each source keeps 150 ms in hand and its speed is trimmed by at most half a
percent to hold that: with 60 ms and no trim, one late burst left a source at empty for good, and 2 to 3 %
of the rounds came up short, which is a click each (clicks in a lobby tune went from 7.9 to 0.9 a
second). The mix is at 75 %: the two outputs together clipped. Both go into MPEG-TS segments of about two seconds (Android's muxer has no such
format) posted by an upload thread, over plain HTTP like the game's own requests. Each request has ten seconds in all, the lookup of
the server's name included, which runs on a thread of its own: a server that answers a byte at a time or not at all holds a thread
no longer (`src/live_net.cpp`, which the player for Windows shares; `tests/host/live_net_test.cpp`, which `test_windows.sh` runs
under Wine too, on the player's own sockets). A slow upload or a
warm phone steps the quality down from what the server asks for: to two thirds of its frame rate, then to half
with three quarters of its lines, then to half its lines, with the bitrate at 60, 35 and 20 % (the Standard
quality's 30 fps and 720 lines go to 20 fps, then to 15 fps and 540 lines, then to 360). The network's step comes
back up after a minute of quick uploads, the phone's as it cools, and nothing is sent from thermal status CRITICAL
on. An encoder that breaks while it runs (a codec the system takes back) ends the session, another is tried ten seconds
later, and three in a row give up; a session that ran a minute starts the count over. `debug.arm32.livebreak <seconds>`
takes each session's encoder as broken that long in, to try this out on a phone. The notice comes as a toast. All the threads run at low priority
and only the encoder thread can block on the encoder; a picture with no free texture is left out.

On a Galaxy S26 Ultra at 120 fps, one play of the same song each, with and without live view: 0 of 237 frames
late per two seconds both ways, 0 underrun frames, process CPU 125 % without and 130 to 133 % with it, the
swap 170 us longer for each picture (worst seen 2.3 ms). `arm32/tests/host/live_ts_test.cpp` checks the
segment writer without a phone (`debug.arm32.liveserver <host:port>` asks another server, with `adb
reverse` a test server on the computer). Encoding from a surface takes Android 8 or newer.

The player for Windows broadcasts too (`desktop/live_desktop.cpp`, with its capture in `live_capture.cpp` and its encoder
in `live_mf.cpp`), with a phone's requests and the same stream. At a swap a picture is due at, the frame is scaled with
one blit and turned into the encoder's NV12 by two small draws on the graphics card, and a later swap copies it out once
the GPU is done, so the game never waits for it. Windows' own H.264 and AAC encoders (Media Foundation) make the stream
from those pictures and the player's mix, before its volume.
Windows' H.264 encoder leaves the colours out of its sequence header, so `src/live_sps.cpp` writes BT.709 into it
(`tests/host/live_sps_test.cpp`). The quality steps down as on a phone for a slow upload, and for an encoder that does
not keep up, and comes back up after a minute with time to spare. The conversion's shaders are compiled when the
server first answers, if that is within 20 seconds of the start, at the game's first screens: a broadcast that starts
later, in a song too, then makes only its textures and buffers on the render thread (under Wine 2 ms, where the compile
had taken 762 of the start's 763 ms). A later first answer leaves the compile to the first capture, as a song may be on
by then. Each start's cost is in the log.

**The shim** (`shim/shim.cpp`, `debug.arm32.shim`, on). Phones that can run 32-bit apps never start this
runtime: the manifest's `use32bitAbi` sends them to `lib/armeabi-v7a`, and the game's own libraries run
natively, which is faster. They get `libopendmtq.so` there, with live view and the frame rate from the same
source files (`live.cpp`, `live_net.cpp`, `live_ts.cpp`, `pacing.cpp`, `follow.cpp`, `window_rate.cpp`), built for 32-bit ARM. A line the
patcher adds to `UnityPlayer` loads it right after `libunity.so`, and it rewrites a few imports in the
global offset tables of `libunity.so`, `libil2cpp.so` and `libopenal.so`: EGL for pictures and pacing, `dlopen`
and `dlsym` to reach the later libraries and FMOD's OpenSL ES, and `slCreateEngine`. OpenSL ES objects keep a
pointer to their method table in their own memory, so each one the game makes gets a copy of the table in which
`Enqueue` and a few others come through the shim first: the game's music comes from `libopenal.so` at 44.1
kHz, and FMOD's output is silent. The patcher's Java class `com.opendmtq.Hook` calls in on Unity's main thread
before each render call, where the il2cpp API may be used for the game's frame cap, as `tweaks.cpp` does here.
The game's code is not changed, and nothing else passes through the shim. If it cannot find something it
leaves that alone; after three crashes of the game within a day it does nothing for a day, then tries once more. A fatal signal counts as a crash, and so does a start that never drew a frame; closing the game does not, and a new version of the app starts over.

On the x86_64 emulator's translated 32-bit path (`primaryCpuAbi=armeabi-v7a`), all of this runs: `libopenal.so`
at 44.1 kHz with a peak near full scale, FMOD at 24 kHz with a peak of 0, and H.264 and AAC arriving at the server.

## How the app side works

- **Host side**, in `lib/arm64-v8a`: the runtime plus a proxy library under the name of every
  32-bit library. A proxy's `JNI_OnLoad` starts the guest once, loads the guest library of the
  same name, binds its `Java_*` exports and calls the guest's `JNI_OnLoad`.
- **Guest process:** started once with a small 32-bit program (the agent) as its main program.
  It hands over `dlopen`/`dlsym` and creates guest threads on request.
- **Host threads become guest threads:** the first time a Java thread calls into guest code, the
  agent creates a guest pthread whose clone is handed to the calling thread instead of a new
  host thread, which then owns that guest context for its lifetime. Guest code calling JNI
  therefore runs on the right Java thread with the right `JNIEnv`. Only the agent's own clone is
  handed over, so a guest thread created at the same moment elsewhere keeps its own host thread.
  When the host thread ends, the guest thread ends too: the guest's `pthread_exit` runs on it, so
  its thread-local destructors run (the game's runtimes and collector forget it), and its stack
  and slot are given back. Without that, every short-lived Java thread that once called the game
  left a guest thread behind until the process ran out of them.
- **Blocking calls and signals:** a guest call that can sleep (a futex wait, a read, a sleep) goes
  through `arm32_isys`, which skips it when a signal is ready and can be cut short by the runtime's
  interrupt; one that never blocks (a futex wake) is made directly, so no signal can lose it.
  After a handler, calls are restarted as Linux restarts them under `SA_RESTART`; sleeps, polls
  and timed waits return `EINTR` instead of starting their timeout over.
- **Calls across:** host to guest by pushing a call frame and running until a return trap; guest
  to host through stub functions that trap with `svc`. Calls that can re-enter guest code (all of
  JNI) are carried out after the JIT returns, so the same thread can call into the guest again;
  so are the ones that wait for the GPU or the audio service (`eglSwapBuffers`, fence waits,
  `glFinish`, OpenSL ES `Realize`/`Resume`/`Destroy`), so that a signal for the waiting thread,
  the collector's stop-the-world among them, is handled while it waits.
- **JNI:** a guest `JavaVM`/`JNIEnv` whose function tables point at trap stubs; 32-bit handles
  for local and global references, method and field IDs; strings and arrays copied into guest
  memory and back; direct buffers shadowed; native methods registered from guest code get host
  trampolines that convert the arguments and call the guest function.
- **System APIs:** guest stub libraries for EGL/GLES 2-3, OpenSL ES, `libandroid` and `liblog`,
  generated from the NDK headers; pointers translated, host handles (EGL objects, windows,
  assets) given 32-bit handles, each kind of object its own (a driver's first fence and Android's
  EGL display can both be 1). Mapped GL buffers are copies in guest memory that start as the
  buffer's contents unless the map invalidates them, kept per thread for the next map.

## Build and test

Needs Docker. The Android NDK is fetched once (about 600 MB) unless `ANDROID_NDK` points at one, or one is in
`~/android-sdk/ndk`.

```sh
arm32/build.sh arm64-v8a    # or x86_64 for the emulator
arm32/test.sh [adb-serial]  # pushes the runner and tests, runs them over adb
```

The core also builds for computers, a desktop Linux host (x86-64, glibc) and Windows x64, with the player that runs the
game there (`desktop/`; [the player for Windows](../docs/windows-player.md)). After `build.sh` has fetched Dynarmic and
built the guest programs:

```sh
arm32/build_desktop.sh      # Linux: the runner, the player and their tests, in _work/arm32/build-desktop-x86_64
arm32/test_desktop.sh       # the same guest programs and checks on this machine, and the player's parts
arm32/build_windows.sh arm32run jvmtest audiotest mediatest settingstest livenettest glasstest player    # Windows, cross-built with llvm-mingw
arm32/test_windows.sh       # the Windows programs' tests under Wine
arm32/bundle_windows.sh     # the player for Windows as a release ships it
```

On a computer the runtime takes its switches from the environment only, logs to stderr, and gives the guest the system
properties of an Android 9 phone of no particular make. In place of Android's Java side, the player hosts the game in a
small Java VM of its own (`jvm/`) with the classes the game calls. On Windows a thin layer (`src/win`) gives the core
Linux's system calls (files, memory, threads and futexes, signals as interruptions, sockets); the player draws through
ANGLE (OpenGL ES on Direct3D 11), plays its sound through WASAPI and decodes video with Media Foundation. The game's
window sits in a frame that keeps it between 4:3 and 21:9, the shapes the game lays itself out for, and tells the game of
a new size as Android does (`surfaceChanged`). The mouse is a finger, its wheel a finger's drag, and Escape the phone's
Back key. CI runs the Windows tests under Wine and on Windows itself (`test_windows.ps1`).

`build.sh` fetches Dynarmic at a fixed commit and the 32-bit system libraries from Google's AOSP
system image (checksum checked) into `_work/arm32`, which is not tracked. Those libraries are open source and unchanged, and
their licenses go with them (`NOTICES.txt`, `libc++-LICENSE.txt`, and the image's own notices): see
[License and notice](../docs/notice.md).
