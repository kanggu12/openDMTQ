// dlopen/dlsym/dlclose of a guest library through the guest linker.
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char** argv) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    const char* path = argc > 1 ? argv[1] : "./libplugin.so";
    void* h = dlopen(path, RTLD_NOW);
    if (!h) { printf("FAIL dlopen: %s\n", dlerror()); return 1; }
    int (*add)(int, int) = (int (*)(int, int))dlsym(h, "plugin_add");
    int (*calls)(void) = (int (*)(void))dlsym(h, "plugin_calls");
    int ok = add && calls && add(2, 3) == 1005 && calls() == 1;
    printf("%s dlopen, dlsym and call\n", ok ? "ok  " : "FAIL");
    Dl_info info;
    int ok2 = dladdr((void*)add, &info) && info.dli_sname && info.dli_fname;
    printf("%s dladdr (%s in %s)\n", ok2 ? "ok  " : "FAIL", ok2 ? info.dli_sname : "?", ok2 ? info.dli_fname : "?");
    int ok3 = dlclose(h) == 0;
    printf("%s dlclose\n", ok3 ? "ok  " : "FAIL");
    printf("%s\n", ok && ok2 && ok3 ? "ALL CHECKS PASSED" : "SOME CHECKS FAILED");
    return ok && ok2 && ok3 ? 7 : 1;
}
