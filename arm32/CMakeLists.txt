# arm32 runtime: runs 32-bit ARM Android code on 64-bit-only devices.
cmake_minimum_required(VERSION 3.18)
project(arm32 CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Windows: the C++ library, its unwinder and the thread library linked in, so that a program is one file that runs on
# any Windows without the toolchain's DLLs beside it. Threads made without a size of their own (std::thread, the system's
# and the libraries' threads) get 8 MB of stack as on Linux, not Windows' 1 MB: guest code runs on them, translated code
# and the runtime's frames on top of the host's.
if(WIN32)
  add_link_options(-static -Wl,--stack,8388608)
  # Windows 10's API, which the runtime and the player need (high-resolution waitable timers, WaitOnAddress, the pointer
  # messages of touch screens): the toolchain's headers would otherwise stop at Windows 7's.
  add_compile_definitions(_WIN32_WINNT=0x0A00 WINVER=0x0A00)
  # Resource files: the player's icon and file details (desktop/player.rc).
  enable_language(RC)
endif()

# Dynarmic, with only the 32-bit ARM front end.
set(DYNARMIC_DIR "" CACHE PATH "Dynarmic source tree")
set(DYNARMIC_TESTS OFF CACHE BOOL "" FORCE)
set(DYNARMIC_FRONTENDS "A32" CACHE STRING "" FORCE)
set(DYNARMIC_USE_BUNDLED_EXTERNALS ON CACHE BOOL "" FORCE)
set(DYNARMIC_WARNINGS_AS_ERRORS OFF CACHE BOOL "" FORCE)
add_subdirectory(${DYNARMIC_DIR} dynarmic EXCLUDE_FROM_ALL)

# The runtime core, shared by the command-line runner and the app library.
enable_language(ASM)
if(WIN32)
  # Windows: Linux's interface below the core comes from the runtime's own layer on Win32 (src/win), the interruptible
  # system call with it.
  set(ARM32_HOST_ASM src/win/files.cpp src/win/sys.cpp src/win/net.cpp src/win/winsock.cpp src/win/mem.cpp)
  set(ARM32_JNI_ENTRY src/jni_entry_win64.S)
elseif(ANDROID_ABI STREQUAL "arm64-v8a")
  set(ARM32_HOST_ASM src/isys_arm64.S)
  set(ARM32_JNI_ENTRY src/jni_entry_arm64.S)
else()
  set(ARM32_HOST_ASM src/isys_x86_64.S)
  set(ARM32_JNI_ENTRY src/jni_entry_x86_64.S)
endif()
add_library(arm32core STATIC src/log.cpp src/memory.cpp src/loader.cpp src/thread.cpp src/syscalls.cpp src/guest.cpp src/diag.cpp
            ${ARM32_HOST_ASM})
set_target_properties(arm32core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_compile_options(arm32core PRIVATE -Wall -Wextra -Wno-unused-parameter)
if(WIN32)
  # Linux's headers as the layer gives them, before the system's; no old POSIX names from the C runtime, whose calls
  # are not Linux's; 64-bit offsets; the lean Windows headers.
  find_package(Threads REQUIRED)
  target_include_directories(arm32core BEFORE PUBLIC src/win/include)
  target_compile_definitions(arm32core PUBLIC NO_OLDNAMES _FILE_OFFSET_BITS=64 WIN32_LEAN_AND_MEAN NOMINMAX)
  # Linux's interface before anything else in every C++ file (arm32_linux.h says why), not in the assembly files; the
  # file that talks to Winsock keeps out of it.
  target_compile_options(arm32core PUBLIC "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include arm32_linux.h>")
  set_source_files_properties(src/win/winsock.cpp PROPERTIES COMPILE_DEFINITIONS ARM32_NO_LINUX)
  target_link_libraries(arm32core PUBLIC dynarmic Threads::Threads ws2_32 synchronization psapi)
elseif(ANDROID)
  target_link_libraries(arm32core PUBLIC dynarmic log)
else()
  # A desktop host (glibc): threads and dlopen from the C library, no Android log.
  find_package(Threads REQUIRED)
  target_link_libraries(arm32core PUBLIC dynarmic Threads::Threads ${CMAKE_DL_LIBS})
endif()

add_executable(arm32run src/main.cpp)
target_compile_options(arm32run PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(arm32run PRIVATE arm32core)

# A host without Android has no Java VM of its own: the one in arm32/jvm (C++, with the classes the game calls) stands in
# for the phone's, and its tests run on the host. The rest of this file is the app library for Android.
if(NOT ANDROID)
  # jni.h is the NDK's, copied by build_desktop.sh: the same types the Android build has.
  set(JNI_INCLUDE_DIR "" CACHE PATH "Folder with jni.h")
  # Native methods are called by the host's own calling convention: System V on Linux, Microsoft's x64 on Windows.
  if(WIN32)
    set(JVM_CALL_ASM jvm/call_win64.S)
  else()
    set(JVM_CALL_ASM jvm/call_x86_64.S)
  endif()
  add_library(jvm STATIC jvm/vm.cpp jvm/jni.cpp jvm/lang.cpp ${JVM_CALL_ASM})
  target_include_directories(jvm PUBLIC jvm ${JNI_INCLUDE_DIR})
  target_compile_options(jvm PRIVATE -Wall -Wextra -Wno-unused-parameter)
  target_link_libraries(jvm PUBLIC Threads::Threads)
  add_executable(jvmtest jvm/test.cpp)
  target_compile_options(jvmtest PRIVATE -Wall -Wextra -Wno-unused-parameter)
  target_link_libraries(jvmtest PRIVATE jvm)
  # What the desktop player does differently on each host: its window, its sound output and its video decoders (X11,
  # PulseAudio and FFmpeg on Linux; Win32, WASAPI and Media Foundation on Windows), and the libraries those need.
  if(WIN32)
    set(WIN_DEPS "" CACHE PATH "Folder with ANGLE's DLLs, the EGL and GLES headers and zlib (arm32/build_windows.sh)")
    set(PLAYER_WINDOW desktop/window_win32.cpp desktop/overlay_win32.cpp desktop/error_box_win32.cpp desktop/player.rc)
    set(PLAYER_OUTPUT desktop/output_wasapi.cpp)
    set(PLAYER_DECODER desktop/decoder_mf.cpp)
    set(PLAYER_SYSTEM_INCLUDE ${WIN_DEPS}/include)
    set(PLAYER_OUTPUT_LIBS ole32 avrt ksuser)
    # Media Foundation itself is loaded when a video plays (decoder_mf.cpp); its GUIDs are mfuuid's.
    set(PLAYER_DECODER_LIBS mfuuid ole32)
    # DXGI waits for the display's refreshes, IMM is the text field's input method (window_win32.cpp).
    # oleaut32: the broadcast's encoder settings come as VARIANTs (live_desktop.cpp); GDI+ draws the overlay and the error
    # box (overlay_win32.cpp, error_box_win32.cpp).
    set(PLAYER_LIBS ${WIN_DEPS}/lib/libzlib1.dll.a user32 gdi32 shell32 dxgi imm32 oleaut32 gdiplus ${PLAYER_OUTPUT_LIBS} ${PLAYER_DECODER_LIBS})
    # The POSIX calls in the player's own files (open, pread, the clocks) are the runtime's Windows layer's, which
    # arm32core carries: the tests of those files need it as the player does.
    set(PLAYER_POSIX arm32core)
  else()
    find_package(X11 REQUIRED)
    find_package(ZLIB REQUIRED)
    set(PLAYER_WINDOW desktop/window_x11.cpp)
    set(PLAYER_OUTPUT desktop/output_pulse.cpp)
    set(PLAYER_DECODER desktop/decoder_ffmpeg.cpp)
    set(PLAYER_SYSTEM_INCLUDE)
    set(PLAYER_OUTPUT_LIBS)
    set(PLAYER_DECODER_LIBS)
    set(PLAYER_LIBS X11::X11 ZLIB::ZLIB)
    set(PLAYER_POSIX)
  endif()
  # The desktop player's video reader and decoders, and their tests on a file FFmpeg's tool makes (arm32/desktop/mp4.h).
  add_executable(mediatest desktop/mediatest.cpp desktop/mp4.cpp desktop/decoder.cpp ${PLAYER_DECODER})
  target_include_directories(mediatest PRIVATE desktop)
  target_compile_options(mediatest PRIVATE -Wall -Wextra -Wno-unused-parameter)
  target_link_libraries(mediatest PRIVATE jvm ${PLAYER_POSIX} ${PLAYER_DECODER_LIBS})
  # The desktop player's PC settings file, as the PC client writes it (arm32/desktop/settings.cpp).
  add_executable(settingstest desktop/settingstest.cpp desktop/settings.cpp)
  target_include_directories(settingstest PRIVATE desktop src)
  target_compile_options(settingstest PRIVATE -Wall -Wextra -Wno-unused-parameter)
  target_link_libraries(settingstest PRIVATE jvm ${PLAYER_POSIX})
  # The desktop player's mixer and its tests, on the host alone (arm32/desktop/mixer.h).
  add_executable(audiotest desktop/audiotest.cpp desktop/mixer.cpp ${PLAYER_OUTPUT})
  target_include_directories(audiotest PRIVATE desktop)
  target_compile_options(audiotest PRIVATE -Wall -Wextra -Wno-unused-parameter)
  target_link_libraries(audiotest PRIVATE jvm ${PLAYER_POSIX} ${PLAYER_OUTPUT_LIBS})
  # The broadcast's requests (src/live_net.cpp) on Windows, through the sockets of the runtime's layer the player's own
  # are: the test CI runs on Linux (tests/host/live_net_test.cpp), with its stand-in servers on 127.0.0.1, under Wine.
  if(WIN32)
    add_executable(livenettest tests/host/live_net_test.cpp src/live_net.cpp)
    target_include_directories(livenettest PRIVATE src)
    target_compile_options(livenettest PRIVATE -Wall -Wextra)
    target_link_libraries(livenettest PRIVATE ${PLAYER_POSIX})
  endif()
  # The desktop player: the runtime and the JNI bridge on that VM (arm32/desktop). The bridges are the app's own (EGL,
  # GL, the Android API and OpenSL ES, with the generated GL thunks); the desktop files stand in for the phone's Java and
  # libandroid.
  set(ARM32_GEN_DIR "" CACHE PATH "Folder with the generated bridge sources")
  add_executable(player desktop/main.cpp desktop/logd.cpp desktop/java_lang.cpp desktop/threads.cpp desktop/android_os.cpp desktop/unity.cpp
                 desktop/android_app.cpp desktop/audio.cpp desktop/mixer.cpp ${PLAYER_OUTPUT} desktop/media.cpp desktop/mp4.cpp desktop/decoder.cpp
                 ${PLAYER_DECODER} desktop/sdk.cpp desktop/web.cpp desktop/http.cpp desktop/pmangplus.cpp desktop/input.cpp desktop/ndk.cpp ${PLAYER_WINDOW} desktop/frames.cpp
                 desktop/own_folder.cpp desktop/settings.cpp desktop/live_desktop.cpp src/live_net.cpp src/live_ts.cpp src/live_sps.cpp
                 src/jni_bridge.cpp ${ARM32_JNI_ENTRY} src/android_bridge.cpp src/egl_bridge.cpp src/gl_special.cpp ${ARM32_GEN_DIR}/gl_thunks.cpp
                 src/opensl_bridge.cpp src/pacing.cpp src/follow.cpp src/window_rate.cpp src/tweaks.cpp)
  target_include_directories(player PRIVATE src desktop ${ARM32_GEN_DIR})
  target_include_directories(player SYSTEM PRIVATE ${PLAYER_SYSTEM_INCLUDE})
  # The NDK's API level macros before every C++ file (desktop/ndk_macros.h says why); SHELL keeps -include and its file
  # together, which CMake would otherwise take apart.
  target_compile_options(player PRIVATE -Wall -Wextra -Wno-unused-parameter -Wno-unused-function
                         "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include ${CMAKE_CURRENT_SOURCE_DIR}/desktop/ndk_macros.h>")
  target_link_libraries(player PRIVATE arm32core jvm ${PLAYER_LIBS})
  if(WIN32)
    # A program with a window and no console: a double click opens no console window beside it. Its output still goes
    # where the one who starts it sends it (own_folder.cpp sends it to a log).
    target_link_options(player PRIVATE -mwindows)
    # The icon the resource file names, from the server launcher's folder.
    set_property(SOURCE desktop/player.rc APPEND PROPERTY COMPILE_OPTIONS "-I${CMAKE_CURRENT_SOURCE_DIR}/../host/windows"
                 "-I${CMAKE_CURRENT_SOURCE_DIR}/desktop")
    # ANGLE's DLLs and the ones they need beside the player, where Windows looks first when it loads them.
    add_custom_command(TARGET player POST_BUILD COMMAND ${CMAKE_COMMAND} -E copy_if_different ${WIN_DEPS}/bin/libEGL.dll
                       ${WIN_DEPS}/bin/libGLESv2.dll ${WIN_DEPS}/bin/zlib1.dll ${WIN_DEPS}/bin/libgcc_s_seh-1.dll
                       ${WIN_DEPS}/bin/libstdc++-6.dll ${WIN_DEPS}/bin/libwinpthread-1.dll $<TARGET_FILE_DIR:player>)
  endif()
  return()
endif()

# In an app: the runtime with the JNI bridge, and the proxy that stands in for each 32-bit
# JNI library.
# Generated by build.sh: the GL thunks and the numbers of the hand-written bridges' stubs.
set(ARM32_GEN_DIR "" CACHE PATH "Folder with the generated bridge sources")
add_library(arm32 SHARED src/app.cpp src/jni_bridge.cpp src/tweaks.cpp ${ARM32_JNI_ENTRY}
            src/gl_special.cpp ${ARM32_GEN_DIR}/gl_thunks.cpp src/egl_bridge.cpp src/pacing.cpp src/follow.cpp src/android_bridge.cpp src/opensl_bridge.cpp src/live.cpp src/live_net.cpp src/live_ts.cpp src/focus_watch.cpp src/window_rate.cpp)
target_include_directories(arm32 PRIVATE src ${ARM32_GEN_DIR})
target_compile_options(arm32 PRIVATE -Wall -Wextra -Wno-unused-parameter -Wno-unused-function)
target_link_libraries(arm32 PRIVATE arm32core android OpenSLES)
# 16 KB segment alignment: Android 15 and later phones may use 16 KB pages and refuse to load
# libraries aligned for 4 KB.
target_link_options(arm32 PRIVATE -Wl,-z,max-page-size=16384)
target_link_options(arm32 PRIVATE -Wl,--exclude-libs,ALL)

add_library(arm32proxy SHARED src/proxy.cpp)
target_link_options(arm32proxy PRIVATE -Wl,-z,max-page-size=16384)
target_link_libraries(arm32proxy PRIVATE arm32)
