// Threads and their queues: java.lang.Thread; android.os.Looper, Handler, Message and HandlerThread, as Android
// delivers messages and runnables; and android.view.Choreographer, whose frame callbacks run on the looper they were
// posted from, at the display's next refresh, with that refresh's time (the game's C# paces its frames by them).
#include "player.h"

#include <algorithm>
#include <ctime>
#include <map>
#include <sys/prctl.h>
#include <thread>

namespace player {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// ---------------------------------------------------------------------------------------------------------------------
// The looper itself.

void Looper::post(std::function<void()> job, Clock::time_point at, const void* owner, int what, const jvm::Object* runnable) {
    {
        std::lock_guard<std::mutex> l(lock_);
        jobs_.push_back(Job{at, next_order_++, std::move(job), owner, what, runnable});
    }
    posted_.notify_all();
}

void Looper::remove(const void* owner, int what, const jvm::Object* runnable) {
    // Destroyed outside the lock: a job's captures may hold the last reference to an object.
    std::deque<Job> gone;
    std::lock_guard<std::mutex> l(lock_);
    for (auto it = jobs_.begin(); it != jobs_.end();) {
        bool match = it->owner == owner && (what >= 0 ? it->what == what : runnable ? it->runnable == runnable : true);
        if (match) {
            gone.push_back(std::move(*it));
            it = jobs_.erase(it);
        } else {
            ++it;
        }
    }
}

bool Looper::has(const void* owner, int what) {
    std::lock_guard<std::mutex> l(lock_);
    return std::any_of(jobs_.begin(), jobs_.end(), [&](const Job& j) { return j.owner == owner && j.what == what; });
}

Looper::Clock::time_point Looper::run_due() {
    const auto now = Clock::now();
    // Only jobs posted before this call: a job that posts another for now (a message loop's next step) waits for the
    // next call, as the Unity main thread's frames need.
    std::uint64_t before;
    {
        std::lock_guard<std::mutex> l(lock_);
        before = next_order_;
    }
    for (;;) {
        std::function<void()> fn;
        {
            std::lock_guard<std::mutex> l(lock_);
            auto best = jobs_.end();
            for (auto it = jobs_.begin(); it != jobs_.end(); ++it) {
                if (it->at > now || it->order >= before) continue;
                if (best == jobs_.end() || it->at < best->at || (it->at == best->at && it->order < best->order)) best = it;
            }
            if (best == jobs_.end()) {
                auto next = Clock::time_point::max();
                for (const Job& j : jobs_) next = std::min(next, j.at);
                return next;
            }
            fn = std::move(best->fn);
            jobs_.erase(best);
        }
        fn();
    }
}

void Looper::wait(Clock::time_point until) {
    std::unique_lock<std::mutex> l(lock_);
    std::uint64_t seen = next_order_;
    posted_.wait_until(l, until, [&] { return next_order_ != seen || quitting.load(); });
}

namespace {

Class* g_looper_class = nullptr;
thread_local Ref<Looper> t_looper;

}  // namespace

void name_thread(const char* name) {
    // Linux's name for the calling thread (15 bytes at most), which the stats and a debugger show; on Windows the
    // runtime's layer makes it the thread's description.
    prctl(PR_SET_NAME, name);
}

Looper& main_looper() {
    static Ref<Looper>* l = new Ref<Looper>(new Looper(g_looper_class));
    return **l;
}

Looper& unity_looper() {
    static Ref<Looper>* l = new Ref<Looper>(new Looper(g_looper_class));
    return **l;
}

Looper* current_looper() { return t_looper.get(); }

Looper& prepare_looper(Looper* looper) {
    t_looper = Ref<Looper>(looper ? looper : new Looper(g_looper_class));
    return *t_looper;
}

namespace {

// Runs a looper on the calling thread until it quits (Looper.loop, a HandlerThread's run).
void loop(Looper& l) {
    while (!l.quitting.load()) {
        auto next = l.run_due();
        l.wait(next);
    }
}

// A job's failure: Android would end the app with the exception; the player logs it and goes on.
void report(jvm::Env& e, const char* where) {
    if (!e.pending) return;
    std::string what = e.pending->cls()->java_name();
    e.pending = {};
    jvm::log("player: %s threw %s", where, what.c_str());
}

// ---------------------------------------------------------------------------------------------------------------------
// Threads.

// The Thread object of the calling thread: the one it was started as, or one made for it (the main thread, the Unity
// main thread, threads the game's native code made).
thread_local Ref<JThread> t_thread;
Class* g_thread_class = nullptr;

JThread& current_thread() {
    if (!t_thread) {
        t_thread = Ref<JThread>(new JThread(g_thread_class));
        t_thread->name = "Thread-" + std::to_string(t_thread->id);
        t_thread->state = 1;
    }
    return *t_thread;
}

JThread& thread_of(Call& c) { return c.self_as<JThread>(); }

void define_thread() {
    Class& t = jvm::define("java/lang/Thread");
    t.interfaces.push_back(jvm::find_class("java/lang/Runnable"));
    g_thread_class = &t;
    // Subclasses (HandlerThread, Unity's WWW) are threads too: the maker up the chain makes their objects.
    t.make = [](Class& k) -> Object* { return new JThread(&k); };
    auto init = [](Call& c, Object* target, const std::string& name) {
        JThread& th = thread_of(c);
        th.target = Ref<Object>(target);
        th.name = name.empty() ? "Thread-" + std::to_string(th.id) : name;
        return Value();
    };
    t.method("<init>", "()V", [init](Call& c) { return init(c, nullptr, ""); });
    t.method("<init>", "(Ljava/lang/Runnable;)V", [init](Call& c) { return init(c, c.l(0), ""); });
    t.method("<init>", "(Ljava/lang/Runnable;Ljava/lang/String;)V", [init](Call& c) { return init(c, c.l(0), c.str(1)); });
    t.method("<init>", "(Ljava/lang/String;)V", [init](Call& c) { return init(c, nullptr, c.str(0)); });
    t.method("<init>", "(Ljava/lang/ThreadGroup;Ljava/lang/Runnable;)V", [init](Call& c) { return init(c, c.l(1), ""); });
    t.method("<init>", "(Ljava/lang/ThreadGroup;Ljava/lang/Runnable;Ljava/lang/String;)V", [init](Call& c) { return init(c, c.l(1), c.str(2)); });
    t.method("<init>", "(Ljava/lang/ThreadGroup;Ljava/lang/Runnable;Ljava/lang/String;J)V", [init](Call& c) { return init(c, c.l(1), c.str(2)); });
    t.method("<init>", "(Ljava/lang/ThreadGroup;Ljava/lang/String;)V", [init](Call& c) { return init(c, nullptr, c.str(1)); });
    // run(): the target's, unless a subclass has its own.
    t.method("run", "()V", [](Call& c) {
        JThread& th = thread_of(c);
        if (th.target) c.env.call(th.target.get(), "run", "()V");
        return Value();
    });
    t.method("start", "()V", [](Call& c) {
        JThread& th = thread_of(c);
        int expected = 0;
        if (!th.state.compare_exchange_strong(expected, 1)) jvm::throw_new("java/lang/IllegalThreadStateException", "already started");
        Ref<JThread> keep(&th);
        std::thread([keep] {
            jvm::Env& e = jvm::attach();
            t_thread = keep;
            e.call(keep.get(), "run", "()V");
            report(e, ("thread " + keep->name).c_str());
            {
                std::lock_guard<std::mutex> l(keep->lock);
                keep->state = 2;
            }
            keep->ended.notify_all();
            t_thread = {};
            jvm::detach();
        }).detach();
        return Value();
    });
    auto join = [](JThread& th, jlong ms) {
        std::unique_lock<std::mutex> l(th.lock);
        auto done = [&th] { return th.state.load() != 1; };
        if (ms > 0) th.ended.wait_for(l, std::chrono::milliseconds(ms), done);
        else th.ended.wait(l, done);
    };
    t.method("join", "()V", [join](Call& c) {
        join(thread_of(c), 0);
        return Value();
    });
    t.method("join", "(J)V", [join](Call& c) {
        join(thread_of(c), c.j(0));
        return Value();
    });
    t.method("isAlive", "()Z", [](Call& c) { return Value::Z(thread_of(c).state.load() == 1); });
    t.method("getName", "()Ljava/lang/String;", [](Call& c) { return Value(jvm::string(thread_of(c).name)); });
    t.method("setName", "(Ljava/lang/String;)V", [](Call& c) {
        thread_of(c).name = c.str(0);
        return Value();
    });
    t.method("getId", "()J", [](Call& c) { return Value::J(thread_of(c).id); });
    t.method("getPriority", "()I", [](Call& c) { return Value::I(thread_of(c).priority); });
    t.method("setPriority", "(I)V", [](Call& c) {
        thread_of(c).priority = c.i(0);
        return Value();
    });
    t.method("isDaemon", "()Z", [](Call& c) { return Value::Z(thread_of(c).daemon); });
    t.method("setDaemon", "(Z)V", [](Call& c) {
        thread_of(c).daemon = c.z(0);
        return Value();
    });
    t.method("interrupt", "()V", [](Call& c) {
        thread_of(c).interrupted = true;
        return Value();
    });
    t.method("isInterrupted", "()Z", [](Call& c) { return Value::Z(thread_of(c).interrupted.load()); });
    t.static_method("interrupted", "()Z", [](Call&) { return Value::Z(current_thread().interrupted.exchange(false)); });
    t.static_method("currentThread", "()Ljava/lang/Thread;", [](Call&) { return Value(&current_thread()); });
    t.static_method("sleep", "(J)V", [](Call& c) {
        std::this_thread::sleep_for(std::chrono::milliseconds(std::max<jlong>(0, c.j(0))));
        return Value();
    });
    t.static_method("sleep", "(JI)V", [](Call& c) {
        std::this_thread::sleep_for(std::chrono::milliseconds(std::max<jlong>(0, c.j(0))) + std::chrono::nanoseconds(c.i(1)));
        return Value();
    });
    t.static_method("yield", "()V", [](Call&) {
        std::this_thread::yield();
        return Value();
    });
    jvm::define("java/lang/ThreadGroup");
    jvm::define("java/lang/IllegalThreadStateException", "java/lang/IllegalArgumentException");
}

// ---------------------------------------------------------------------------------------------------------------------
// Messages and handlers.

Class* g_message_class = nullptr;
jvm::Field *g_what = nullptr, *g_arg1 = nullptr, *g_arg2 = nullptr, *g_obj = nullptr;

// android.os.Message: what, arg1, arg2 and obj are Java fields (native code reads them with GetIntField); the target
// handler and a runnable are the message's own.
class Message : public Object {
public:
    using Object::Object;
    Ref<Object> target, callback;
};

class Handler : public Object {
public:
    using Object::Object;
    Ref<Looper> looper;
    Ref<Object> callback;
};

Ref<Message> new_message(Object* target, jint what, jint arg1, jint arg2, Object* obj) {
    Ref<Message> m(new Message(g_message_class));
    m->target = Ref<Object>(target);
    m->set_field(g_what, Value::I(what));
    m->set_field(g_arg1, Value::I(arg1));
    m->set_field(g_arg2, Value::I(arg2));
    m->set_field(g_obj, Value(obj));
    return m;
}

// Handler.dispatchMessage: a message's runnable; else the handler's callback (a C# proxy, often), and when that does not
// take it, the handler's own handleMessage.
void dispatch(Handler& h, Message& m) {
    jvm::Env& e = jvm::attach();
    if (m.callback) {
        e.call(m.callback.get(), "run", "()V");
    } else {
        bool handled = h.callback && e.call(h.callback.get(), "handleMessage", "(Landroid/os/Message;)Z", {Value(&m)}).z();
        if (!e.pending && !handled) e.call(&h, "handleMessage", "(Landroid/os/Message;)V", {Value(&m)});
    }
    report(e, "a message's handler");
}

// Puts a message on its handler's looper, due at `at`.
bool enqueue(Handler& h, Ref<Message> m, Looper::Clock::time_point at) {
    if (!h.looper || h.looper->quitting.load()) return false;
    Ref<Handler> keep(&h);
    jint what = m->callback ? -1 : m->field(g_what).i();
    h.looper->post([keep, m] { dispatch(*keep, *m); }, at, &h, what, m->callback.get());
    return true;
}

Looper::Clock::time_point after_ms(jlong ms) { return Looper::Clock::now() + std::chrono::milliseconds(std::max<jlong>(0, ms)); }

Handler& handler_of(Call& c) { return c.self_as<Handler>(); }

void define_handlers() {
    jvm::define_interface("java/lang/Runnable").declare("run", "()V");
    jvm::define_interface("android/os/Handler$Callback").declare("handleMessage", "(Landroid/os/Message;)Z");
    Class& lc = jvm::define("android/os/Looper");
    g_looper_class = &lc;
    lc.static_method("getMainLooper", "()Landroid/os/Looper;", [](Call&) { return Value(&main_looper()); });
    lc.static_method("myLooper", "()Landroid/os/Looper;", [](Call&) { return Value(current_looper()); });
    lc.static_method("prepare", "()V", [](Call&) {
        if (current_looper()) jvm::throw_new("java/lang/RuntimeException", "Only one Looper may be created per thread");
        prepare_looper();
        return Value();
    });
    lc.static_method("loop", "()V", [](Call&) {
        Looper* l = current_looper();
        if (!l) jvm::throw_new("java/lang/RuntimeException", "No Looper; Looper.prepare() wasn't called on this thread.");
        loop(*l);
        return Value();
    });
    auto quit = [](Call& c) {
        auto& l = c.self_as<Looper>();
        l.quitting = true;
        l.post([] {});
        return Value();
    };
    lc.method("quit", "()V", quit);
    lc.method("quitSafely", "()V", quit);

    Class& mc = jvm::define("android/os/Message");
    g_message_class = &mc;
    mc.field("what", "I").field("arg1", "I").field("arg2", "I").field("obj", "Ljava/lang/Object;");
    g_what = mc.find_field("what", false);
    g_arg1 = mc.find_field("arg1", false);
    g_arg2 = mc.find_field("arg2", false);
    g_obj = mc.find_field("obj", false);
    mc.make = [](Class& k) -> Object* { return new Message(&k); };
    mc.method("<init>", "()V", [](Call&) { return Value(); });
    mc.static_method("obtain", "()Landroid/os/Message;", [](Call&) { return Value(new_message(nullptr, 0, 0, 0, nullptr)); });
    mc.static_method("obtain", "(Landroid/os/Handler;)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.l(0), 0, 0, 0, nullptr)); });
    mc.static_method("obtain", "(Landroid/os/Handler;I)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.l(0), c.i(1), 0, 0, nullptr)); });
    mc.static_method("obtain", "(Landroid/os/Handler;ILjava/lang/Object;)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.l(0), c.i(1), 0, 0, c.l(2))); });
    mc.static_method("obtain", "(Landroid/os/Handler;III)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.l(0), c.i(1), c.i(2), c.i(3), nullptr)); });
    mc.static_method("obtain", "(Landroid/os/Handler;IIILjava/lang/Object;)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.l(0), c.i(1), c.i(2), c.i(3), c.l(4))); });
    mc.static_method("obtain", "(Landroid/os/Handler;Ljava/lang/Runnable;)Landroid/os/Message;", [](Call& c) {
        Ref<Message> m = new_message(c.l(0), 0, 0, 0, nullptr);
        m->callback = Ref<Object>(c.l(1));
        return Value(m);
    });
    mc.method("getTarget", "()Landroid/os/Handler;", [](Call& c) { return Value(c.self_as<Message>().target); });
    mc.method("setTarget", "(Landroid/os/Handler;)V", [](Call& c) {
        c.self_as<Message>().target = Ref<Object>(c.l(0));
        return Value();
    });
    mc.method("sendToTarget", "()V", [](Call& c) {
        auto& m = c.self_as<Message>();
        auto* h = dynamic_cast<Handler*>(m.target.get());
        if (!h) jvm::throw_new("java/lang/NullPointerException", "a message without a target");
        enqueue(*h, Ref<Message>(&m), Looper::Clock::now());
        return Value();
    });
    mc.method("recycle", "()V", [](Call&) { return Value(); });

    Class& hc = jvm::define("android/os/Handler");
    hc.make = [](Class& k) -> Object* { return new Handler(&k); };
    // A handler takes the calling thread's looper unless it is given one, and fails without one, as Android's does.
    auto init = [](Call& c, Looper* looper, Object* callback) {
        Handler& h = handler_of(c);
        if (!looper) looper = current_looper();
        if (!looper) jvm::throw_new("java/lang/RuntimeException", "Can't create handler inside thread that has not called Looper.prepare()");
        h.looper = Ref<Looper>(looper);
        h.callback = Ref<Object>(callback);
        return Value();
    };
    hc.method("<init>", "()V", [init](Call& c) { return init(c, nullptr, nullptr); });
    hc.method("<init>", "(Landroid/os/Looper;)V", [init](Call& c) { return init(c, c.as<Looper>(0), nullptr); });
    hc.method("<init>", "(Landroid/os/Looper;Landroid/os/Handler$Callback;)V", [init](Call& c) { return init(c, c.as<Looper>(0), c.l(1)); });
    hc.method("<init>", "(Landroid/os/Handler$Callback;)V", [init](Call& c) { return init(c, nullptr, c.l(0)); });
    hc.method("getLooper", "()Landroid/os/Looper;", [](Call& c) { return Value(handler_of(c).looper); });
    hc.method("handleMessage", "(Landroid/os/Message;)V", [](Call&) { return Value(); });
    hc.method("dispatchMessage", "(Landroid/os/Message;)V", [](Call& c) {
        if (auto* m = c.as<Message>(0)) dispatch(handler_of(c), *m);
        return Value();
    });
    auto post = [](Call& c, Object* runnable, Looper::Clock::time_point at) {
        Ref<Message> m = new_message(c.self, 0, 0, 0, nullptr);
        m->callback = Ref<Object>(runnable);
        return Value::Z(enqueue(handler_of(c), m, at));
    };
    hc.method("post", "(Ljava/lang/Runnable;)Z", [post](Call& c) { return post(c, c.l(0), Looper::Clock::now()); });
    hc.method("postDelayed", "(Ljava/lang/Runnable;J)Z", [post](Call& c) { return post(c, c.l(0), after_ms(c.j(1))); });
    hc.method("postAtFrontOfQueue", "(Ljava/lang/Runnable;)Z", [post](Call& c) { return post(c, c.l(0), Looper::Clock::time_point::min()); });
    auto send = [](Call& c, Message* m, Looper::Clock::time_point at) {
        if (!m) jvm::throw_new("java/lang/NullPointerException", "sendMessage(null)");
        m->target = Ref<Object>(c.self);
        return Value::Z(enqueue(handler_of(c), Ref<Message>(m), at));
    };
    hc.method("sendMessage", "(Landroid/os/Message;)Z", [send](Call& c) { return send(c, c.as<Message>(0), Looper::Clock::now()); });
    hc.method("sendMessageDelayed", "(Landroid/os/Message;J)Z", [send](Call& c) { return send(c, c.as<Message>(0), after_ms(c.j(1))); });
    hc.method("sendMessageAtFrontOfQueue", "(Landroid/os/Message;)Z", [send](Call& c) { return send(c, c.as<Message>(0), Looper::Clock::time_point::min()); });
    hc.method("sendEmptyMessage", "(I)Z", [](Call& c) { return Value::Z(enqueue(handler_of(c), new_message(c.self, c.i(0), 0, 0, nullptr), Looper::Clock::now())); });
    hc.method("sendEmptyMessageDelayed", "(IJ)Z", [](Call& c) { return Value::Z(enqueue(handler_of(c), new_message(c.self, c.i(0), 0, 0, nullptr), after_ms(c.j(1)))); });
    hc.method("obtainMessage", "()Landroid/os/Message;", [](Call& c) { return Value(new_message(c.self, 0, 0, 0, nullptr)); });
    hc.method("obtainMessage", "(I)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.self, c.i(0), 0, 0, nullptr)); });
    hc.method("obtainMessage", "(ILjava/lang/Object;)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.self, c.i(0), 0, 0, c.l(1))); });
    hc.method("obtainMessage", "(III)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.self, c.i(0), c.i(1), c.i(2), nullptr)); });
    hc.method("obtainMessage", "(IIILjava/lang/Object;)Landroid/os/Message;", [](Call& c) { return Value(new_message(c.self, c.i(0), c.i(1), c.i(2), c.l(3))); });
    hc.method("removeMessages", "(I)V", [](Call& c) {
        handler_of(c).looper->remove(c.self, c.i(0), nullptr);
        return Value();
    });
    hc.method("removeCallbacks", "(Ljava/lang/Runnable;)V", [](Call& c) {
        if (c.l(0)) handler_of(c).looper->remove(c.self, -1, c.l(0));
        return Value();
    });
    hc.method("removeCallbacksAndMessages", "(Ljava/lang/Object;)V", [](Call& c) {
        handler_of(c).looper->remove(c.self, -1, nullptr);
        return Value();
    });
    hc.method("hasMessages", "(I)Z", [](Call& c) { return Value::Z(handler_of(c).looper->has(c.self, c.i(0))); });
}

// android.os.HandlerThread: a thread whose run() is a looper; getLooper() waits until it has one.
class HandlerThread : public JThread {
public:
    using JThread::JThread;
    Ref<Looper> looper;
    std::condition_variable has_looper;
};

void define_handler_thread() {
    Class& c = jvm::define("android/os/HandlerThread", "java/lang/Thread");
    c.make = [](Class& k) -> Object* { return new HandlerThread(&k); };
    auto init = [](Call& c) {
        auto& t = c.self_as<HandlerThread>();
        t.name = c.str(0);
        return Value();
    };
    c.method("<init>", "(Ljava/lang/String;)V", init);
    c.method("<init>", "(Ljava/lang/String;I)V", init);
    c.method("run", "()V", [](Call& c) {
        auto& t = c.self_as<HandlerThread>();
        Looper& l = prepare_looper();
        {
            std::lock_guard<std::mutex> g(t.lock);
            t.looper = Ref<Looper>(&l);
        }
        t.has_looper.notify_all();
        loop(l);
        return Value();
    });
    c.method("getLooper", "()Landroid/os/Looper;", [](Call& c) {
        auto& t = c.self_as<HandlerThread>();
        // Not started: null, as Android gives; started: once its looper exists.
        if (t.state.load() == 0) return Value();
        std::unique_lock<std::mutex> g(t.lock);
        t.has_looper.wait(g, [&t] { return t.looper || t.state.load() == 2; });
        return Value(t.looper);
    });
    auto quit = [](Call& c) {
        auto& t = c.self_as<HandlerThread>();
        std::lock_guard<std::mutex> g(t.lock);
        if (!t.looper) return Value::Z(false);
        t.looper->quitting = true;
        t.looper->post([] {});
        return Value::Z(true);
    };
    c.method("quit", "()Z", quit);
    c.method("quitSafely", "()Z", quit);
}

// ---------------------------------------------------------------------------------------------------------------------
// Choreographer: one per looper thread, frame callbacks at the display's refreshes.

class Choreographer : public Object {
public:
    using Object::Object;
    Ref<Looper> looper;
};

// The monotonic clock in nanoseconds, the clock of System.nanoTime and of frame times.
jlong mono_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<jlong>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
}

// The first refresh at or after `ns`: refreshes fall on whole periods of the display's rate.
jlong refresh_at_or_after(jlong ns) {
    double rate = app().refresh > 1 ? app().refresh : 60.0;
    auto period = static_cast<jlong>(1e9 / rate);
    return (ns + period - 1) / period * period;
}

void define_choreographer() {
    jvm::define_interface("android/view/Choreographer$FrameCallback").declare("doFrame", "(J)V");
    Class& c = jvm::define("android/view/Choreographer");
    c.static_method("getInstance", "()Landroid/view/Choreographer;", [&c](Call&) {
        Looper* l = current_looper();
        if (!l) jvm::throw_new("java/lang/IllegalStateException", "The current thread must have a looper!");
        static std::mutex lock;
        static std::map<Looper*, Ref<Choreographer>> by_looper;
        std::lock_guard<std::mutex> g(lock);
        Ref<Choreographer>& ch = by_looper[l];
        if (!ch) {
            ch = Ref<Choreographer>(new Choreographer(&c));
            ch->looper = Ref<Looper>(l);
        }
        return Value(ch);
    });
    auto post = [](Call& c, Object* callback, jlong delay_ms) {
        auto& ch = c.self_as<Choreographer>();
        if (!callback) jvm::throw_new("java/lang/IllegalArgumentException", "callback must not be null");
        // The refresh the callback is for, and its time, which doFrame gets.
        jlong frame = refresh_at_or_after(mono_ns() + std::max<jlong>(0, delay_ms) * 1000000);
        auto at = Looper::Clock::now() + std::chrono::nanoseconds(frame - mono_ns());
        Ref<Object> cb(callback);
        ch.looper->post(
            [cb, frame] {
                jvm::Env& e = jvm::attach();
                e.call(cb.get(), "doFrame", "(J)V", {Value::J(frame)});
                report(e, "a frame callback");
            },
            at, &ch, -1, callback);
        return Value();
    };
    c.method("postFrameCallback", "(Landroid/view/Choreographer$FrameCallback;)V", [post](Call& c) { return post(c, c.l(0), 0); });
    c.method("postFrameCallbackDelayed", "(Landroid/view/Choreographer$FrameCallback;J)V", [post](Call& c) { return post(c, c.l(0), c.j(1)); });
    c.method("removeFrameCallback", "(Landroid/view/Choreographer$FrameCallback;)V", [](Call& c) {
        auto& ch = c.self_as<Choreographer>();
        if (c.l(0)) ch.looper->remove(&ch, -1, c.l(0));
        return Value();
    });
    // SystemClock and System's clocks: the same monotonic clock, and wall time.
    Class& sc = jvm::define("android/os/SystemClock");
    sc.static_method("uptimeMillis", "()J", [](Call&) { return Value::J(mono_ns() / 1000000); });
    sc.static_method("elapsedRealtime", "()J", [](Call&) { return Value::J(mono_ns() / 1000000); });
    sc.static_method("elapsedRealtimeNanos", "()J", [](Call&) { return Value::J(mono_ns()); });
    sc.static_method("sleep", "(J)V", [](Call& c) {
        std::this_thread::sleep_for(std::chrono::milliseconds(std::max<jlong>(0, c.j(0))));
        return Value();
    });
    Class& sys = jvm::define("java/lang/System");
    sys.static_method("nanoTime", "()J", [](Call&) { return Value::J(mono_ns()); });
    sys.static_method("currentTimeMillis", "()J", [](Call&) {
        timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        return Value::J(static_cast<jlong>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000);
    });
}

}  // namespace

void define_threads() {
    define_handlers();
    define_thread();
    define_handler_thread();
    define_choreographer();
}

}  // namespace player
