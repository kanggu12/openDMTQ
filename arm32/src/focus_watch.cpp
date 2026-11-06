// Keeps Unity's idea of the window's focus true to Android's.
//
// Opening the game while a package update is being finished (Samsung's PackageUpdateActivity brings the
// app to the front a second time) pauses and resumes the activity at once. Then Unity's Java side can
// be left having told the game "focus lost" as its last word, while Android says the window has focus
// and the activity is resumed: the game stays paused on a black screen until the player leaves
// and comes back. Seen in about one start in three right after installing an update, on a Galaxy S26
// Ultra, with and without any other change here.
//
// So a thread looks every two seconds. Twice in a row of "the window has focus, the game thinks not"
// and it tells UnityPlayer again, as the activity would: windowFocusChanged(true), then resume(). Both
// do nothing new when the game is already running. While the game is away from the screen Android
// also says no focus, and nothing happens.
#include "jni_bridge.h"
#include "pacing.h"
#include "runtime.h"

#include <chrono>
#include <csignal>
#include <pthread.h>
#include <sys/resource.h>
#include <system_error>
#include <thread>
#include <unistd.h>

namespace arm32 {

namespace {

JavaVM* g_vm = nullptr;
jclass g_player_class = nullptr;  // com.unity3d.player.UnityPlayer
jclass g_activity_class = nullptr;  // com.unity3d.player.UnityPlayerActivity

void clear(JNIEnv* e) {
    if (e->ExceptionCheck()) e->ExceptionClear();
}

// One look: tells the game again at the second mismatch in a row.
void check(JNIEnv* e, int* mismatches) {
    jfieldID current = e->GetStaticFieldID(g_player_class, "currentActivity", "Landroid/app/Activity;");
    jobject activity = current ? e->GetStaticObjectField(g_player_class, current) : nullptr;
    clear(e);
    if (!activity) return;
    jclass activity_class = e->GetObjectClass(activity);
    jmethodID has_focus = e->GetMethodID(activity_class, "hasWindowFocus", "()Z");
    const bool focused = has_focus && e->CallBooleanMethod(activity, has_focus);
    clear(e);
    if (!focused || jni_game_has_focus()) {
        *mismatches = 0;
    } else if (++*mismatches >= 2) {
        *mismatches = 0;
        jfieldID field = e->IsInstanceOf(activity, g_activity_class) ? e->GetFieldID(g_activity_class, "mUnityPlayer", "Lcom/unity3d/player/UnityPlayer;") : nullptr;
        jobject player = field ? e->GetObjectField(activity, field) : nullptr;
        clear(e);
        if (player) {
            log("arm32: the window has focus but the game was told otherwise: telling it again");
            jmethodID changed = e->GetMethodID(g_player_class, "windowFocusChanged", "(Z)V");
            jmethodID resume = e->GetMethodID(g_player_class, "resume", "()V");
            if (changed) e->CallVoidMethod(player, changed, JNI_TRUE);
            clear(e);
            if (resume) e->CallVoidMethod(player, resume);
            clear(e);
            e->DeleteLocalRef(player);
        }
    }
    e->DeleteLocalRef(activity_class);
    e->DeleteLocalRef(activity);
}

void watch() {
    // Nothing to do with the guest's signals, and never in the game's way.
    sigset_t all;
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, nullptr);
    pthread_setname_np(pthread_self(), "arm32-focus");
    setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), 10);
    JNIEnv* e = nullptr;
    if (g_vm->AttachCurrentThread(&e, nullptr) != JNI_OK) return;
    int mismatches = 0;
    for (int turn = 0;; ++turn) {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        check(e, &mismatches);
        // This thread being here anyway: how hot the phone says it is, for the frame rate.
        if (turn % 5 == 0) pacing_thermal_tick();
    }
}

jclass keep(JNIEnv* e, const char* name) {
    jclass local = e->FindClass(name);
    clear(e);
    if (!local) return nullptr;
    auto global = static_cast<jclass>(e->NewGlobalRef(local));
    e->DeleteLocalRef(local);
    return global;
}

}  // namespace

void focus_watch_start(JavaVM* vm, JNIEnv* env) {
    g_vm = vm;
    g_player_class = keep(env, "com/unity3d/player/UnityPlayer");
    g_activity_class = keep(env, "com/unity3d/player/UnityPlayerActivity");
    if (!g_player_class || !g_activity_class) return;
    // Without a thread the game just goes on as it did before this watch.
    try {
        std::thread(watch).detach();
    } catch (const std::system_error&) {
        log("arm32: cannot start the focus watch");
    }
}

}  // namespace arm32
