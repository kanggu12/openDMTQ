// Stand-in for a 32-bit JNI library, installed under its name: loading it loads the 32-bit
// library of the same name in the guest and runs that library's JNI_OnLoad.
#include <dlfcn.h>
#include <jni.h>

extern "C" jint arm32_proxy_onload(JavaVM* vm, const char* self_path);

extern "C" JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void*) {
    Dl_info info{};
    dladdr(reinterpret_cast<void*>(&JNI_OnLoad), &info);
    return arm32_proxy_onload(vm, info.dli_fname);
}
