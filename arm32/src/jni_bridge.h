// JNI across the 32/64-bit boundary.
//
// Guest code gets a JavaVM and a JNIEnv whose function tables point at trap stubs; each JNI
// function runs on the host with the calling thread's real JNIEnv, after converting 32-bit
// handles, IDs, strings and arrays. Native methods that guest code registers get host
// trampolines that convert the arguments and run the guest function on the calling thread.
#pragma once

#include "guest.h"

#include <jni.h>

namespace arm32 {

// Sets up the guest JavaVM and JNIEnv for the host VM. Call once, after Guest::start().
void jni_init(JavaVM* vm);

// Guest addresses of the guest JavaVM and JNIEnv (the same JNIEnv serves every thread; the
// host side looks up the calling thread's own).
gaddr jni_guest_vm();
gaddr jni_guest_env();

// Remembers the host JNIEnv of the calling thread.
void jni_set_env(JNIEnv* env);

// Runs guest JNI_OnLoad(vm, reserved) on the calling thread and returns its JNI version.
jint jni_call_onload(gaddr fn);

// Registers the guest library's Java_* functions (handle from Guest::dlopen, file the 32-bit
// library on the host) as the native methods they name, which the host VM would otherwise
// look up by name in the host library. Call it in the proxy's JNI_OnLoad, where FindClass
// sees the app's classes, and before the library's JNI_OnLoad, whose own registrations win.
void jni_bind_exports(JNIEnv* e, gaddr handle, const std::string& file);

// What Unity's native code was last told about the window's focus (nativeFocusChanged).
bool jni_game_has_focus();

// Watches for the window having focus while Unity believes it has not (focus_watch.cpp). Call where
// FindClass sees the app's classes.
void focus_watch_start(JavaVM* vm, JNIEnv* env);

// For other bridges that take JNI arguments (ANativeWindow_fromSurface, AAssetManager_fromJava):
// the calling thread's host JNIEnv, and the host object behind a guest reference handle.
JNIEnv* jni_env();
jobject jni_object(std::uint32_t handle);

}  // namespace arm32
