// The player's window on a desktop Linux host: an X11 window that the game's EGL surface draws into. The window's id is
// what the game gets as its ANativeWindow (ndk.cpp), and what the host's EGL takes as the native window, so the
// runtime's EGL bridge passes it on as it is. The Java side is an android.view.Surface naming the window.
#include "player.h"

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/XKBlib.h>
#include <X11/keysym.h>
#include <algorithm>
#include <cstdlib>

namespace player {

namespace {

Display* g_display = nullptr;
Window g_window = 0;
// The window manager's close button arrives as this message.
Atom g_delete = 0;
// Whether the mouse's first button is down (a finger on the screen).
bool g_pressed = false;
// Escape held as the phone's Back key (pump_window).
bool g_back_down = false;

// android.view.Surface: the window it stands for.
class Surface : public jvm::Object {
public:
    Surface(jvm::Class* cls, std::uintptr_t window) : Object(cls), window(window) {}
    const std::uintptr_t window;
};

jvm::Ref<jvm::Object> g_surface;

}  // namespace

bool open_window(const std::string& title) {
    // The game's threads and this one may all reach Xlib (EGL keeps a connection of its own as well).
    XInitThreads();
    g_display = XOpenDisplay(nullptr);
    if (!g_display) {
        const char* d = std::getenv("DISPLAY");
        jvm::log("player: cannot open the X display %s", d ? d : "(DISPLAY is not set)");
        return false;
    }
    int screen = DefaultScreen(g_display);
    if (app().fit_screen) {
        // As on Windows: three quarters of the screen's height at 16:9, no wider than nine tenths of it.
        int w = DisplayWidth(g_display, screen), h = DisplayHeight(g_display, screen);
        app().height = h * 3 / 4;
        app().width = app().height * 16 / 9;
        if (app().width > w * 9 / 10) {
            app().width = w * 9 / 10;
            app().height = app().width * 9 / 16;
        }
    }
    g_window = XCreateSimpleWindow(g_display, RootWindow(g_display, screen), 0, 0, static_cast<unsigned>(app().width), static_cast<unsigned>(app().height), 0,
                                   BlackPixel(g_display, screen), BlackPixel(g_display, screen));
    XStoreName(g_display, g_window, title.c_str());
    g_delete = XInternAtom(g_display, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(g_display, g_window, &g_delete, 1);
    // Size changes and closing now; keys, buttons and motion for the input the player will hand the game.
    XSelectInput(g_display, g_window, StructureNotifyMask | ExposureMask | KeyPressMask | KeyReleaseMask | ButtonPressMask | ButtonReleaseMask | PointerMotionMask | FocusChangeMask);
    XMapWindow(g_display, g_window);
    // The surface is only good once the window is on the screen.
    for (XEvent e;;) {
        XNextEvent(g_display, &e);
        if (e.type == MapNotify) break;
    }
    g_surface = jvm::Ref<jvm::Object>(new Surface(&jvm::define("android/view/Surface"), g_window));
    return true;
}

jvm::Object* surface() { return g_surface.get(); }

std::uintptr_t window_of(jvm::Object* surface) {
    auto* s = dynamic_cast<Surface*>(surface);
    return s ? s->window : 0;
}

void wait_for_events(Looper::Clock::time_point until) {
    // Window events come in through no queue of ours: looked at again within 4 ms whatever is due.
    main_looper().wait(std::min(until, Looper::Clock::now() + std::chrono::milliseconds(4)));
}

// The keyboard types into the game's text as it is (pump_window): nothing to open.
void soft_keyboard(bool) {}

bool pump_window() {
    // A held key gives presses only, not a release before each (its release then means it was let go).
    static const bool detectable = XkbSetDetectableAutoRepeat(g_display, True, nullptr);
    (void)detectable;
    while (XPending(g_display)) {
        XEvent e;
        XNextEvent(g_display, &e);
        if (e.type == ClientMessage && static_cast<Atom>(e.xclient.data.l[0]) == g_delete) return false;
        // The size ANativeWindow reports follows the window's, and the game hears of a new one as on a phone.
        if (e.type == ConfigureNotify && (e.xconfigure.width != app().width || e.xconfigure.height != app().height)) {
            app().width = e.xconfigure.width;
            app().height = e.xconfigure.height;
            surface_changed();
        }
        // Keys type into the soft keyboard while the game asks for text: text as text, and the keys that end or edit it.
        if (e.type == KeyPress && typing()) {
            char text[32];
            KeySym sym = 0;
            int n = XLookupString(&e.xkey, text, sizeof text, &sym, nullptr);
            if (sym == XK_Return || sym == XK_KP_Enter) type_key(kKeyEnter);
            else if (sym == XK_Escape) type_key(kKeyEscape);
            else if (sym == XK_BackSpace) type_key(kKeyBackspace);
            else if (n > 0 && static_cast<unsigned char>(text[0]) >= 0x20) type_text(std::string(text, static_cast<std::size_t>(n)));
        } else if ((e.type == KeyPress || e.type == KeyRelease) && XLookupKeysym(&e.xkey, 0) == XK_Escape) {
            // Otherwise Escape is the phone's Back key, as on Windows (window_win32.cpp): down once, up only after a down
            // of its own (not after the Escape that ended a text), however long it is held.
            if (e.type == KeyPress && !g_back_down) {
                g_back_down = true;
                key(kKeycodeBack, true, 0, 0);
            } else if (e.type == KeyRelease && g_back_down) {
                g_back_down = false;
                key(kKeycodeBack, false, 0, 0);
            }
        }
        // The wheel's buttons (4 and 5 up and down, 6 and 7 sideways) are a finger's drag that scrolls, a notch each.
        if (e.type == ButtonPress && e.xbutton.button >= 4 && e.xbutton.button <= 7 && !g_pressed) {
            const unsigned b = e.xbutton.button;
            const float notch = b == 4 || b == 7 ? 1.0f : -1.0f;
            wheel(static_cast<float>(e.xbutton.x), static_cast<float>(e.xbutton.y), b >= 6 ? notch : 0.0f, b >= 6 ? 0.0f : notch);
        }
        // The mouse's first button is a finger: pressed, moved while pressed, lifted.
        if (e.type == ButtonPress && e.xbutton.button == Button1) {
            g_pressed = true;
            touch(0, static_cast<float>(e.xbutton.x), static_cast<float>(e.xbutton.y));
        } else if (e.type == MotionNotify && g_pressed) {
            touch(2, static_cast<float>(e.xmotion.x), static_cast<float>(e.xmotion.y));
        } else if (e.type == ButtonRelease && e.xbutton.button == Button1 && g_pressed) {
            g_pressed = false;
            touch(1, static_cast<float>(e.xbutton.x), static_cast<float>(e.xbutton.y));
        }
    }
    return true;
}

}  // namespace player
