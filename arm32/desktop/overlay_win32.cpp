// What the player for Windows draws over the game itself (window_win32.cpp places and feeds it), as frosted glass in the
// game's own shapes and colours: the game shows through each piece, blurred, under a charcoal tint, with a light edge
// and the game's bevel (a line of light along the top, of shade along the foot) and a soft shadow under it
// (overlay_glass.h makes the glass); its corners small as the game's, its green line along the bar's and the notice's
// foot. The game's lime marks what is lit, red what is live; the buttons are the launcher's own (overlay_glass.h). Each
// piece is a layered window of its own above the game's window, shown with UpdateLayeredWindow from a premultiplied
// 32-bit picture, so its edges are smooth and its fades cost the game nothing. The game's frame behind a piece comes from
// the render thread (glass_capture.h), read at a quarter of its size while a piece is up, at most 20 times a second; a
// piece is drawn again only when what is behind it changed. Before a frame has been read, a piece waits for one (150 ms
// at most), then shows its bare tint, solid enough to read.
//
// Two threads share the work. The window's own thread (the UI thread, which also stamps every key and click for the
// game) keeps the windows, what they show and when, and hands each finished picture to UpdateLayeredWindow. A thread of
// the overlay's own, the painter, makes the pictures: the blur and the tint of the frame behind, GDI+'s words and
// shapes. The UI thread hands it an order (what the piece shows, the game's area, the last read) and goes on at once;
// the picture comes back as a message, so a key pressed meanwhile is never stamped late for it.
//
// - The bar: a PC has no phone's buttons around the game, so a bar of glass across the top of the game's area comes down
//   when the pointer moves to the very top edge or onto the handle and rests there with its button up, or when a finger
//   is drawn down from the top edge, either only with the game quiet (no click, touch or held note) for 1.5 s; by
//   itself for 3 seconds when the game's picture first shows and after each switch between a window and full screen,
//   so that a player sees where it is. The OpenDMTQ wordmark on its left, as the launcher's header draws it;
//   on its right three of the launcher's buttons, minimise and full screen (or back to a window) as its quiet metal
//   secondary buttons, a lighter plate under the pointer, and an X that quits after asking as its lime main button from
//   the start; held, a button is sunk. The window itself has no buttons: the game is minimised, put in full screen and
//   quit from here. It stays while the pointer is on it and goes up soon after it leaves, so it never sits on the
//   game's own controls at the top while they are used. No key brings it.
// - Its motion: the bar slides down out of the game's top edge, its foot first, and back up into it (overlay_motion.h:
//   a fifth of a second, slowing into its place; a little quicker up, gathering speed), never over the window's title
//   bar above: its window shows only the part of its picture that is below the edge. A step comes with each refresh of
//   the display and only places pictures made before. The notice and a counter in a top corner move with its foot. A
//   way turned back midway (the pointer back on it, the question) goes on from where it is. Where Windows shows no
//   animations, it comes and goes at once.
// - The handle: the game's green line along its top edge at the centre (a short piece of the bar's own foot line),
//   with a small tab of glass hanging from it in the lean of the game's own tabs and a chevron pointing down in the
//   tab, which says that a bar comes down from here; with the pointer on it, lime and a little deeper. As large as the
//   game's header leaves room for, at the game's own scale, so that it covers no button and no word of the game's (it
//   stands on the top end of the header's hairline divider, which is at the centre: overlay_scale.h). Clicks go through
//   it to the game; the pointer resting on it brings the bar down, and the handle then goes down with the bar's foot,
//   fading, and comes back up with it. Hidden while the bar is down, while the question or a notice is up, while the
//   game is held, and before the game's first picture.
// - The question before quitting: the bar's X and the taskbar's Close window ask it. The game dims and blurs behind a
//   card of glass with the question, the game's green line under it, a thin X, Keep playing as the launcher's lime main
//   button and Quit the game as its secondary, red under the pointer; the keys' choice in the launcher's cyan keyboard
//   ring. The game holds still meanwhile, so a click by mistake mid-song loses nothing. Asked over a minimised window,
//   the window comes back and the game draws its picture again before it holds, so the question shows over the game,
//   not over black. Alt+F4, F11 and Alt+Enter do nothing.
// - The notice: the server's two-line notice about a broadcast (a title, then where to watch), as a glass card that
//   slides down at the top of the game, stays for a few seconds and fades, stepped with the display as the bar is. A
//   red LIVE tag with a slanted end, as the game's tags, while broadcasting; once the broadcast has ended its title
//   says so alone, with no tag.
// - The cursor: a dart in the logo's chrome and lime, all lime while the mouse's finger is down on the game.
// - The frame counter: when the PC's settings ask for it, a small glass box like the game's Q and MAX box, at the bottom
//   right, where it covers the fewest of the game's own labels and buttons, unless another corner is chosen (at the top
//   left, beside a song's pause button), 8 pixels in at 720 lines, at the smaller of the two scales the game stretches
//   its layout by (overlay_scale.h), as the handle is: FPS in the game's lime, the frames a second in white
//   and the mean frame time under them, over the last second, from the count of frames shown that the player keeps
//   anyway (frames.cpp; frame_rate.h says how it reads it). The whole of it faint
//   (its window at 62 % opacity), so the game shows through. Hidden until the game's first frame and while the game is
//   held still, never a 0 that the overlay itself caused. It lets clicks through.
#include "overlay_win32.h"

// GDI+ and the picture it draws into, which the error box before the game draws with too (error_box_win32.cpp).
#include "canvas_win32.h"
// The game's frame behind the glass, read on the render thread; the glass and the faces.
#include "glass_capture.h"
#include "overlay_glass.h"
// The overlay's scale, the game's own with a floor at Windows' scale; the handle's own scale and its tab's sizes.
#include "overlay_scale.h"
// The bar's way down and up, and the handle's part in it.
#include "overlay_motion.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace player::overlay {

namespace {

using namespace Gdiplus;

HWND g_frame = nullptr, g_game = nullptr;
Hooks g_hooks{};
bool g_korean = false;
ULONG_PTR g_gdiplus = 0;

// What a piece is drawn for: the game's area's size, Windows' scale of its display, the room the bar takes at the top
// while it is down, and whether the frame is in full screen. The UI thread reads them from the windows; the painter
// draws for the ones its order carries, set for its thread while it draws (Drawing below).
struct View {
    int w = 1, h = 1;
    float dpi = 1;
    int top_room = 0;
    bool full = false;
};
// The view the thread draws for now (null: the windows' own, on the UI thread).
thread_local const View* t_view = nullptr;

// A view set for the thread while a piece is drawn for it.
struct Drawing {
    const View* before;
    explicit Drawing(const View& v) : before(t_view) { t_view = &v; }
    ~Drawing() { t_view = before; }
    Drawing(const Drawing&) = delete;
    Drawing& operator=(const Drawing&) = delete;
};

#ifdef OVERLAY_TEST_HOOKS
// The probe's stand-in for Windows' scale (0: Windows' own), so that 150 % can be drawn on a PC at 100 %.
float g_test_dpi = 0;
// The probe's pictures without their words: the glass under the words alone, for their contrast.
bool g_test_no_words = false;
// The probe draws only: no window is ever shown or moved.
bool g_test_quiet = false;
// Where the words of the piece being drawn went and in what colour, for the probe's measure of their contrast, and
// whether they were cut to fit their box (an ellipsis in their place), which no look may do.
struct TestText {
    Gdiplus::RectF box;
    Gdiplus::Color colour;
    bool cut = false;
};
std::vector<TestText>* g_test_texts = nullptr;
// Where the bar's last look put its name (the wordmark), for the probe's check that the chips keep clear of it.
Gdiplus::RectF g_test_bar_name;
#endif

// Whether a window may be shown: never while the probe draws.
bool showing() {
#ifdef OVERLAY_TEST_HOOKS
    return !g_test_quiet;
#else
    return true;
#endif
}

// Whether words are drawn (the probe leaves them out for the glass under them alone).
bool words() {
#ifdef OVERLAY_TEST_HOOKS
    return !g_test_no_words;
#else
    return true;
#endif
}

// Windows' scale of the frame's display now (1 at 96 dpi), as the UI thread reads it.
float window_dpi() {
#ifdef OVERLAY_TEST_HOOKS
    // The probe's scale, when it set one.
    if (g_test_dpi > 0) return g_test_dpi;
#endif
    using DpiOf = UINT(WINAPI*)(HWND);
    // Windows 10 1607 has the call; an older one is taken as 96 dpi.
    static auto dpi_of = reinterpret_cast<DpiOf>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
    return (dpi_of && g_frame ? static_cast<float>(dpi_of(g_frame)) : 96.0f) / 96.0f;
}

// The scale of the game's display a piece is drawn for: the painter's order's, else the window's own.
float dpi_scale() { return t_view ? t_view->dpi : window_dpi(); }

// The game's area on the screen (the UI thread's: the windows are its own).
RECT area() {
    RECT r{};
    // The game's own window, or the frame before it is made.
    GetWindowRect(g_game ? g_game : g_frame, &r);
    return r;
}

// The game's area's size: the view's while a piece is drawn for one, else the window's now.
int area_w() {
    if (t_view) return t_view->w;
    const RECT a = area();
    return std::max(1, static_cast<int>(a.right - a.left));
}
int area_h() {
    if (t_view) return t_view->h;
    const RECT a = area();
    return std::max(1, static_cast<int>(a.bottom - a.top));
}

// A cap on the scale while one piece is laid out and drawn (0: none): the question's card, which keeps within the
// game's area (AskScale below). Each thread its own: the UI thread lays the card out for its clicks while the painter
// draws it.
thread_local float t_scale_cap = 0;

// The overlay's scale: the game's own, which lays itself out for 720 lines and grows with its area (1.5 at 1080 lines, 3
// at 4K), so that the bar, the question, the notice and the counter keep the size of the game's own words and buttons in
// a small window as in a large one, and cover no more of the game on a display at 150 % than at 100 %; never below half
// its 720-line size at Windows' scale, where the bar's buttons are still large enough to hit (overlay_scale.h). The
// painter's view and the UI thread's clicks both come here, so a chip is hit where it is drawn.
float scale() {
    const float s = scale_for(area_h(), dpi_scale());
    // The question's card within its cap while it is laid out or drawn.
    return t_scale_cap > 0 ? std::min(s, t_scale_cap) : s;
}

// The question's card at 720 lines: its width and its height.
constexpr float kCardWidth = 520, kCardHeight = 228;

// The question's card at most three quarters of the game's area wide and nine tenths of it high, everything in it scaled
// with it. The overlay's own scale keeps it well within that (at most 54 % of the area's width, in a 4:3 one, and 42 % of
// its height, in the smallest the window holds): a guard, so that no scale can ever set the card past the game's edges.
// Held while the card is laid out or drawn.
struct AskScale {
    float before;
    AskScale() : before(t_scale_cap) {
        t_scale_cap = std::min(0.75f * static_cast<float>(area_w()) / kCardWidth, 0.9f * static_cast<float>(area_h()) / kCardHeight);
    }
    ~AskScale() { t_scale_cap = before; }
    AskScale(const AskScale&) = delete;
    AskScale& operator=(const AskScale&) = delete;
};

// The frame counter at its own scale while it is laid out and drawn: the smaller of the two the game stretches its
// layout by, never below the overlay's floor (overlay_scale.h's counter_scale_for), which is never above the overlay's
// own, so a cap gives it exactly. The notice, which keeps clear of a counter in a top corner, lays that counter out
// under it too.
struct CounterScale {
    float before;
    CounterScale() : before(t_scale_cap) { t_scale_cap = counter_scale_for(area_w(), area_h(), dpi_scale()); }
    ~CounterScale() { t_scale_cap = before; }
    CounterScale(const CounterScale&) = delete;
    CounterScale& operator=(const CounterScale&) = delete;
};
// A length of the game's at 720 lines as pixels at the overlay's scale, whole (edges on whole pixels stay sharp). Every
// size of the overlay goes through here.
int px(float at720) { return static_cast<int>(std::lround(at720 * scale())); }
// The same, unrounded: a line's width, a blur.
float fpx(float at720) { return at720 * scale(); }

// The shadow under every piece: black at 35 %, blurred 18 (a CSS blur, twice its Gaussian's sigma) and 4 lower, at 720
// lines. The room a piece's window keeps around its glass for it: to its sides, above and below.
constexpr float kShadow = 0.35f, kShadowBlur = 18, kShadowDrop = 4;
constexpr float kRoomSide = 24, kRoomTop = 20, kRoomBottom = 28;
// The glass's blur (a Gaussian's sigma at 720 lines) and its saturation; the question's dim behind its card.
constexpr float kGlassBlur = 10, kGlassSaturation = 1.15f, kDimBlur = 4, kDim = 0.40f;
// The frame counter's window as a whole, glass, words and all: 62 % (158 of 255), so that the game shows through it
// while its words still read (the probe measures them over the game's frames at this opacity).
constexpr BYTE kCounterAlpha = 158;
// A piece wanted on the screen waits this long for its first picture with the frame behind it, then shows its bare
// tint; the bar and the question read ahead, so they rarely wait.
constexpr UINT64 kGlassWaitMs = 150;

// A layered popup owned by the frame: above the game, never taking the focus; `see_through` lets input pass.
HWND make_window(const wchar_t* name, WNDPROC proc, bool see_through) {
    WNDCLASSEXW c{};
    c.cbSize = sizeof c;
    c.lpfnWndProc = proc;
    c.hInstance = GetModuleHandleW(nullptr);
    c.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    c.lpszClassName = name;
    RegisterClassExW(&c);
    // A tool window: none of its own on the taskbar or in Alt+Tab.
    const DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | (see_through ? WS_EX_TRANSPARENT : 0);
    return CreateWindowExW(ex, name, L"", WS_POPUP, 0, 0, 1, 1, g_frame, nullptr, c.hInstance, nullptr);
}

// The mark Windows leaves on a mouse message it made from a touch or a pen (GetMessageExtraInfo): such a message is no
// mouse's.
bool from_touch() { return (GetMessageExtraInfo() & 0xFFFFFF00) == 0xFF515700; }

// A line for the player's log, when the window gave the overlay a way to it.
void note(const char* line) {
    if (g_hooks.log) g_hooks.log(line);
}

// ---- words (the painter's: GDI+ is used on its thread alone, apart from the cursor's own pictures)

// The words' format: set tight (no room of GDI+'s either side), on one line, its spaces measured.
const StringFormat& tight() {
    static const std::unique_ptr<StringFormat> f = [] {
        std::unique_ptr<StringFormat> s(StringFormat::GenericTypographic()->Clone());
        s->SetFormatFlags(s->GetFormatFlags() | StringFormatFlagsNoWrap | StringFormatFlagsMeasureTrailingSpaces);
        return s;
    }();
    return *f;
}

// A text's box as `font` sets it: its advance and its line's height.
RectF measure(const std::wstring& text, const Font& f) {
    // A one-pixel picture to measure on.
    static Bitmap probe(1, 1, PixelFormat32bppPARGB);
    Graphics g(&probe);
    smooth(g);
    RectF box;
    g.MeasureString(text.c_str(), -1, &f, PointF(0, 0), &tight(), &box);
    return box;
}

// The probe's note of words drawn (or that would be), opaque ones only: a faint one under them is no words of its own;
// `cut` when they did not fit their box.
void note_words(RectF box, const Color& colour, bool cut = false) {
#ifdef OVERLAY_TEST_HOOKS
    if (g_test_texts && colour.GetA() == 255) g_test_texts->push_back(TestText{box, colour, cut});
#else
    (void)box;
    (void)colour;
    (void)cut;
#endif
}

// Words with the top left of their line at `at`.
void say(Graphics& g, const std::wstring& text, const Font& f, const Color& colour, PointF at) {
    const RectF size = measure(text, f);
    note_words(RectF(at.X, at.Y, size.Width, size.Height), colour);
    if (!words()) return;
    SolidBrush brush(colour);
    g.DrawString(text.c_str(), -1, &f, at, &tight(), &brush);
}

// Words centred in a box, on one line (cut with an ellipsis where the box is too narrow).
void say_centred(Graphics& g, const std::wstring& text, const Font& f, const Color& colour, RectF box) {
    const RectF size = measure(text, f);
    const float tw = std::min(size.Width, box.Width);
    // Wider than the box by more than rounding: GDI+ cuts them with an ellipsis, which the probe reports.
    note_words(RectF(box.X + (box.Width - tw) / 2, box.Y + (box.Height - size.Height) / 2, tw, size.Height), colour, size.Width > box.Width + 0.5f);
    if (!words()) return;
    std::unique_ptr<StringFormat> centre(tight().Clone());
    centre->SetAlignment(StringAlignmentCenter);
    centre->SetLineAlignment(StringAlignmentCenter);
    centre->SetTrimming(StringTrimmingEllipsisCharacter);
    SolidBrush brush(colour);
    g.DrawString(text.c_str(), -1, &f, box, centre.get(), &brush);
}

// Text broken into lines of at most `room` pixels at its spaces, as Korean is set (GDI+ would break between any two
// Hangul syllables, leaving one alone on a line); a word longer than the room stays whole on its own line.
std::vector<std::wstring> wrap_words(const std::wstring& text, const Font& f, float room) {
    std::vector<std::wstring> lines;
    std::wstring line;
    std::size_t at = 0;
    while (at <= text.size()) {
        std::size_t space = text.find(L' ', at);
        if (space == std::wstring::npos) space = text.size();
        const std::wstring word = text.substr(at, space - at);
        const std::wstring longer = line.empty() ? word : line + L" " + word;
        if (measure(longer, f).Width <= room || line.empty()) {
            line = longer;
        } else {
            lines.push_back(line);
            line = word;
        }
        at = space + 1;
    }
    if (!line.empty()) lines.push_back(line);
    return lines;
}

// The same, its lines made as even as they can be in as few lines: the narrowest room that still takes no more lines
// than the full room does, so that a long line never leaves one word alone under it ("볼 수" / "있어요").
std::vector<std::wstring> wrap_even(const std::wstring& text, const Font& f, float room) {
    auto lines = wrap_words(text, f, room);
    if (lines.size() < 2) return lines;
    // Halving the room between what fits in that many lines and the full room, to within a pixel.
    float low = 0, high = room;
    while (high - low > 1) {
        const float mid = (low + high) / 2;
        if (wrap_words(text, f, mid).size() <= lines.size()) high = mid;
        else low = mid;
    }
    return wrap_words(text, f, high);
}

// ---- the glass's pieces, as the painter makes them

// The pictures the painter has made so far: each new one gets the next number, so that the UI thread can tell a new
// picture from one it already shows.
std::atomic<unsigned> g_made{0};

// A piece of glass as the painter keeps it: its look, its window's place in the game's area, the frame behind it as
// blurred for that place, and the picture made from them, kept with what it was made from so that it is made again only
// when one of them changed. Two pictures in turn: the one the UI thread may still show, and one to draw the next into.
struct Paint {
    Look look;
    // What its look was made for (its order's look as text: the same text, the same look).
    std::string made_for;
    // A number that changes with every new look.
    int look_serial = 0;
    // The window's place in the game's area.
    int x = 0, y = 0;
    // The handle's alone: the rows of its rail at its picture's top.
    int lip = 0;
    // The frame behind it, blurred, for the place it was made for, and the hash of what it was made from.
    Backdrop backdrop;
    std::uint64_t backdrop_from = 0;
    bool have_backdrop = false;
    // The picture made last, and the one before it (drawn into again once the UI thread has let it go).
    std::shared_ptr<Canvas> picture, spare;
    unsigned made = 0;
    // What the picture shows: its look, its frame's hash (0: the bare tint) and its place.
    int drawn_serial = -1;
    std::uint64_t drawn_hash = 1;
    int drawn_x = -1, drawn_y = -1;
};

// The blur's reach around a piece, which the reads take in as well: three sigmas.
int blur_reach() { return px(kGlassBlur * 3); }

// A picture of w by h to draw into: the spare one when the UI thread no longer holds it (only the painter hands
// pictures out, so no other thread can take it back meanwhile), else a new one.
std::shared_ptr<Canvas> free_canvas(std::shared_ptr<Canvas>& spare, int w, int h) {
    if (spare && spare.use_count() == 1 && spare->w == w && spare->h == h) {
        // The UI thread's last use of it (UpdateLayeredWindow reading its pixels) before it let it go, seen before it
        // is drawn into: the count's fall was a release, this the acquire that pairs with it.
        std::atomic_thread_fence(std::memory_order_acquire);
        return std::move(spare);
    }
    return std::make_shared<Canvas>(std::max(1, w), std::max(1, h));
}

// The piece's picture as its look, the frame behind and its place make it now, from the read `shots`; true when it
// changed. The frame behind is blurred again only when what it is made from changed.
bool paint_draw(Paint& p, const std::vector<glass::Shot>& shots) {
    Backdrop raw;
    const bool behind = backdrop_from(shots, glass::Rect{p.x, p.y, p.look.w, p.look.h}, blur_reach(), raw);
    if (behind && (!p.have_backdrop || raw.hash != p.backdrop_from)) {
        p.backdrop_from = raw.hash;
        soften(raw, fpx(kGlassBlur), kGlassSaturation, 0);
        p.backdrop = std::move(raw);
    }
    p.have_backdrop = behind;
    const std::uint64_t hash = behind ? p.backdrop_from : 0;
    if (p.picture && p.drawn_serial == p.look_serial && p.drawn_hash == hash && p.drawn_x == p.x && p.drawn_y == p.y && p.picture->w == p.look.w &&
        p.picture->h == p.look.h) {
        return false;
    }
    std::shared_ptr<Canvas> c = free_canvas(p.spare, p.look.w, p.look.h);
    if (!c->bits) return false;
    // From nothing: a piece alone over the game.
    std::memset(c->bits, 0, static_cast<std::size_t>(c->w) * static_cast<std::size_t>(c->h) * 4);
    compose(*c, 0, 0, p.look, behind ? &p.backdrop : nullptr, p.x, p.y);
    p.spare = std::move(p.picture);
    p.picture = std::move(c);
    p.made = ++g_made;
    p.drawn_serial = p.look_serial;
    p.drawn_hash = hash;
    p.drawn_x = p.x;
    p.drawn_y = p.y;
    return true;
}

// A piece's glass edge: a thin light line around it, lighter along the top, as light catches the top of a pane.
void edge(Graphics& g, RectF r, float radius) {
    GraphicsPath path;
    // On the glass's outermost pixels: half a line in.
    const float line = std::max(1.0f, fpx(1));
    rounded(path, RectF(r.X + line / 2, r.Y + line / 2, r.Width - line, r.Height - line), std::max(0.0f, radius - line / 2));
    // White at 24 % along the top, falling to 12 % by a corner's height down and staying there below.
    const Color stops[] = {Color(61, 255, 255, 255), Color(31, 255, 255, 255), Color(31, 255, 255, 255)};
    LinearGradientBrush lit(PointF(0, r.Y - 1), PointF(0, r.Y + r.Height + 1), stops[0], stops[2]);
    const float bend = std::clamp((std::max(radius, fpx(8)) + 1) / (r.Height + 2), 0.05f, 0.95f);
    const REAL at[] = {0.0f, bend, 1.0f};
    lit.SetInterpolationColors(stops, at, 3);
    Pen pen(&lit, line);
    g.DrawPath(&pen, &path);
}

// A piece's glass shape and shadow: a rounded rectangle `glass` in a window of w by h.
void pane_shape(Look& look, int w, int h, RectF glass, float radius, bool beyond = false) {
    shape(look, w, h, glass, radius, beyond, kShadow, fpx(kShadowBlur), fpx(kShadowDrop));
}

// A new picture for a look's words and lines, of the look's size, cleared.
Graphics* fresh_fore(Look& look, std::unique_ptr<Bitmap>& surface) {
    look.fore = std::make_unique<Canvas>(std::max(1, look.w), std::max(1, look.h));
    if (look.fore->bits) std::memset(look.fore->bits, 0, static_cast<std::size_t>(look.fore->w) * static_cast<std::size_t>(look.fore->h) * 4);
    surface = look.fore->surface();
    auto* g = new Graphics(surface.get());
    smooth(*g);
    return g;
}

// ---- the game's own look, as its frames show it (measured at 1080 lines; sizes here at 720)

namespace game {
// The red of its LIVE tags, light to deep (the notice's tag while a broadcast is live).
const Color kRedTop(255, 0xC4, 0x2B, 0x1C), kRedFoot(255, 0x9E, 0x1F, 0x14);
// The line under its tab row and along its notice band.
const Color kLine(255, 0x64, 0xBB, 0x3E);
// Its Q and MAX box: a green-black fill under a lime border.
constexpr std::uint8_t kBoxTop[3] = {0x16, 0x24, 0x19}, kBoxFoot[3] = {0x0F, 0x17, 0x0B};
}  // namespace game

// The game's bevel inside a piece's edge: a line of light along its top and a line of shade along its foot, clear of
// the corners. `light` and `dark` are their alphas.
void bevel(Graphics& g, RectF r, float radius, BYTE light, BYTE dark) {
    const float line = std::max(1.0f, fpx(1));
    // Inside the glass's own edge: the second pixel row from the top and from the foot.
    const float top = r.Y + line * 1.5f, foot = r.Y + r.Height - line * 1.5f;
    const float x0 = r.X + std::max(radius, line), x1 = r.X + r.Width - std::max(radius, line);
    Pen up(Color(light, 255, 255, 255), line), down(Color(dark, 0, 0, 0), line);
    g.DrawLine(&up, x0, top, x1, top);
    g.DrawLine(&down, x0, foot, x1, foot);
}

// The game's line along an edge: a pixel of its green (or another colour) from x0 to x1 at row y, whole in the middle
// and fading out toward both ends, as the line under its tab row does.
void game_line(Graphics& g, float x0, float x1, float y, const Color& colour) {
    if (x1 <= x0) return;
    const Color clear(0, colour.GetR(), colour.GetG(), colour.GetB());
    const Color stops[] = {clear, colour, colour, clear};
    const REAL at[] = {0.0f, 0.3f, 0.7f, 1.0f};
    // A pixel past both ends, so that the gradient's own ends do not wrap onto the line's.
    LinearGradientBrush brush(PointF(x0 - 1, 0), PointF(x1 + 1, 0), stops[0], stops[3]);
    brush.SetInterpolationColors(stops, at, 4);
    g.FillRectangle(&brush, x0, y, x1 - x0, std::max(1.0f, fpx(1)));
}

// A line's middle where a line `width` wide (a whole number of pixels) has both its edges on whole pixels: crisp, and at
// most half a pixel from where it was asked.
float crisp(float at, float width) { return std::floor(at - width / 2 + 0.5f) + width / 2; }

// ---- the bar's sizes and the room it takes (both threads: the UI thread's clicks, the painter's pictures)

// What is under the pointer on the bar: nothing, the X (at the right end), the full screen chip (left of it) or the
// minimise chip (left of that).
constexpr int kNone = -1, kQuitChip = 0, kScreenChip = 1, kMinChip = 2;
// Whether the pieces at the game's top (the notice, a counter in a top corner) are placed under the bar (the UI
// thread's): from when the bar has come down whole until it has gone up. While the bar is on its way they keep the
// place they had and are moved with it.
bool g_bar_room = false;

// The bar's height, the chips' size, the gap between them and their room from the bar's right end, at this scale
// (overlay_scale.h's bar: 74 at 720 lines, as the game's own X at the top right of its song and music screens reaches
// row 70, its soft edge, measured on the game's frames, and the bar covers it whole with 4 to spare; the X as far in
// from the bar's right end as the wordmark from its left).
int bar_height() { return px(kBarTall); }
int chip_size() { return px(kChipSize); }
int chip_gap() { return px(kChipGap); }

// The room the bar takes at the top of the game's area once it is down (0 once it is up): what sits at the top is
// placed under it rather than being covered. The painter's view says it for the picture it draws.
int top_room() {
    if (t_view) return t_view->top_room;
    return g_bar_room ? bar_height() : 0;
}

// A chip's square on a bar `w` pixels wide: the X at the right end, the full screen chip left of it, minimise left of
// that; each centred in the bar's height.
RectF chip_rect(int which, int w) {
    const float size = static_cast<float>(chip_size());
    // Across: overlay_scale.h's arithmetic, which a check holds to the wordmark's end; down, in the bar's middle.
    const float x = static_cast<float>(chip_left(which, w, scale()));
    return RectF(x, static_cast<float>((bar_height() - chip_size()) / 2), size, size);
}

// The chip under a point of the bar's window, or kNone.
int chip_at(int x, int y) {
    for (int which : {kQuitChip, kScreenChip, kMinChip}) {
        if (chip_rect(which, area_w()).Contains(static_cast<REAL>(x), static_cast<REAL>(y))) return which;
    }
    return kNone;
}

// ---- the handle's size and place (both threads)

// The handle as drawn, at 720 lines (overlay_scale.h has its tab's and its rail's sizes, which checks hold to the game's
// header, and the reach a resting pointer brings the bar from, which keeps to the same room: the tab as drawn hangs
// inside it at rest and lit, and the ends of the rail lit beyond it lie on the game's top edge, where a resting pointer
// brings the bar as well): its rail fading out over three tenths of its length toward either end as the bar's own foot
// line does; the tab's foot corners rounded 3.6 and its outline 2 wide; in the tab a chevron pointing down, 12.6 wide
// and 5.9 deep, its top 5.4 below the edge (8.4 with the pointer on it: pulled down), 2.5 thick.
constexpr float kRailFade = 0.3f;
constexpr float kTabRound = 3.6f, kTabEdge = 2;
constexpr float kChevWide = 12.6f, kChevDeep = 5.9f, kChevTop = 5.4f, kChevTopLit = 8.4f, kChevStroke = 2.5f;
// How strong each part is: the tab's charcoal glass at 78 % with a little light at its top that is gone by its foot;
// the rail and the outline at 95 % at rest, the shade under the rail at 35 %; the chevron at 96 %.
constexpr float kTabGlass = 0.78f, kTabSheen = 0.06f, kHandleLine = 0.95f, kRailShadeAlpha = 0.35f, kChevAlpha = 0.96f;
// The room the handle's window keeps beside and below what is drawn (its smooth edges).
constexpr float kHandleRoom = 4;

// The handle's own scale: the game's exactly, with no floor (overlay_scale.h says why).
float handle_scale() { return handle_scale_for(area_w(), area_h()); }
// A length of the handle's at 720 lines as pixels at its scale, unrounded.
float hpx(float at720) { return at720 * handle_scale(); }

// Whether (x, y) of the game's area is on the handle, as the pointer rests there: its reach (overlay_scale.h), at the
// handle's own scale for the game's area now.
bool on_handle(int x, int y) { return in_handle_reach(x, y, area_w(), area_h()); }

// ---- the frame counter's look (the painter's)

// The counter's glass, as the game's Q and MAX box: its size at this scale, the same whatever its numbers (room for
// three digits and "99.9 ms"): the label FPS on the left, the number on the right, the frame time under the number.
struct FpsMetrics {
    float pad_x, pad_y, gap, cell, number_h, label_w, time_h, w, h;
};
FpsMetrics fps_metrics() {
    FpsMetrics m{};
    auto number = font(Weight::kBold, fpx(18), false);
    auto label = font(Weight::kBold, fpx(11), false);
    auto time = font(Weight::kRegular, fpx(11), false);
    m.pad_x = fpx(10);
    m.pad_y = fpx(6);
    m.gap = fpx(12);
    // Tabular figures: every digit in a cell as wide as the widest, so that the number does not jitter as it changes.
    for (wchar_t d = L'0'; d <= L'9'; ++d) m.cell = std::max(m.cell, measure(std::wstring(1, d), *number).Width);
    m.number_h = measure(L"0", *number).Height;
    m.label_w = measure(L"FPS", *label).Width;
    const RectF t = measure(L"88.8 ms", *time);
    m.time_h = t.Height;
    // The number's line a little tighter than its face's own height: the time sits close under it.
    m.w = std::ceil(m.pad_x * 2 + std::max(m.label_w + m.gap + m.cell * 3, t.Width));
    m.h = std::ceil(m.pad_y * 2 + m.number_h * 0.86f + m.time_h);
    return m;
}

// The counter's glass's top left in its corner (Settings::ShowFps's order: 1 top left, 2 top right, 3 bottom left, 4
// bottom right, its own place), 8 pixels in at 720 lines; top left, 8 pixels right of the game's pause button, so that
// it covers nothing a song uses; in a top corner, under the bar while that is down. At the bottom right, 8 in from the
// right and the foot, it covers the fewest of the game's labels and buttons: none on most of its screens, the end of
// the result's SELECT MUSIC and of the download list's DOWNLOAD, and the loading screen's version (measured on the
// game's frames at 720 and 1080 lines: 9 of 37; the bottom left 13, its music list's grid button whole). The pause
// button is as wide as the game's width says in every shape (overlay_scale.h's counter_at), so beside it the counter
// keeps its 8 at 21:9, where the height's scale would put it on the button, and at 4:3. Laid out at the counter's own
// scale (CounterScale), as its look is.
POINT fps_place(int corner, int chip_w, int chip_h) {
    const CounterAt at = counter_at(corner, area_w(), area_h(), px(8), chip_w, chip_h, top_room());
    return POINT{at.x, at.y};
}

// A piece's window around its glass at (gx, gy) of gw by gh: the shadow's room on every side, within the game's area.
RECT window_around(int gx, int gy, int gw, int gh) {
    RECT r{gx - px(kRoomSide), gy - px(kRoomTop), gx + gw + px(kRoomSide), gy + gh + px(kRoomBottom)};
    r.left = std::max(0L, r.left);
    r.top = std::max(0L, r.top);
    r.right = std::min(static_cast<LONG>(area_w()), r.right);
    r.bottom = std::min(static_cast<LONG>(area_h()), r.bottom);
    return r;
}

// The counter's look for `fps` frames a second and `ms` a frame (fps below 0: not measured yet, dashes) in `corner`:
// the game's Q and MAX box in glass, its green-black over the frame, a pixel of lime around it, the label in lime, the
// number white and bold, the time grey. Its window's place goes to the paint.
void fps_look(Paint& p, int fps, float ms, int corner) {
    const FpsMetrics m = fps_metrics();
    const POINT at = fps_place(corner, static_cast<int>(m.w), static_cast<int>(m.h));
    const RECT chip{at.x, at.y, at.x + static_cast<LONG>(m.w), at.y + static_cast<LONG>(m.h)};
    const RECT win = window_around(chip.left, chip.top, static_cast<int>(m.w), static_cast<int>(m.h));
    p.x = win.left;
    p.y = win.top;
    Look& look = p.look;
    const int w = win.right - win.left, h = win.bottom - win.top;
    const RectF glass(static_cast<REAL>(chip.left - win.left), static_cast<REAL>(chip.top - win.top), static_cast<REAL>(chip.right - chip.left),
                      static_cast<REAL>(chip.bottom - chip.top));
    const float radius = fpx(4);
    pane_shape(look, w, h, glass, radius);
    look.tint = kTintPiece;
    std::copy(game::kBoxTop, game::kBoxTop + 3, look.tint_top);
    std::copy(game::kBoxFoot, game::kBoxFoot + 3, look.tint_foot);
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(look, surface));
    // Its border: a pixel of the game's lime at 55 %, on the glass's outermost pixels; the game's bevel inside it.
    {
        const float line = std::max(1.0f, fpx(1));
        GraphicsPath border;
        rounded(border, RectF(glass.X + line / 2, glass.Y + line / 2, glass.Width - line, glass.Height - line), std::max(0.0f, radius - line / 2));
        Pen lime(Color(140, tone::kLime.GetR(), tone::kLime.GetG(), tone::kLime.GetB()), line);
        g->DrawPath(&lime, &border);
        bevel(*g, glass, radius, 26, 60);
    }
    auto number = font(Weight::kBold, fpx(18), false);
    auto label = font(Weight::kBold, fpx(11), false);
    auto time_font = font(Weight::kRegular, fpx(11), false);
    const float top = glass.Y + m.pad_y;
    const float right = glass.X + glass.Width - m.pad_x;
    // The number, right-aligned digit by digit in cells as wide as the widest digit; before the first measure, a dash
    // as wide as two of them.
    if (fps < 0) {
        const std::wstring dash = L"--";
        say(*g, dash, *number, Color(255, 255, 255, 255), PointF(right - m.cell * 2 + (m.cell * 2 - measure(dash, *number).Width) / 2, top));
    } else {
        const std::wstring digits = std::to_wstring(fps);
        float x = right - m.cell * static_cast<float>(digits.size());
        for (wchar_t d : digits) {
            const std::wstring one(1, d);
            // Each digit in the middle of its cell.
            say(*g, one, *number, Color(255, 255, 255, 255), PointF(x + (m.cell - measure(one, *number).Width) / 2, top));
            x += m.cell;
        }
    }
    // FPS in lime on the left, on the number's foot: the bottom of the number's line less the face's room below its
    // digits.
    const float foot = top + m.number_h * 0.80f;
    const float label_h = measure(L"FPS", *label).Height;
    say(*g, L"FPS", *label, tone::kLime, PointF(glass.X + m.pad_x, foot - label_h * 0.80f));
    // The mean frame time under the number, grey, right-aligned; none to give (not measured yet, or no frame in the
    // last look's time): dashes.
    wchar_t time[32];
    if (fps <= 0) std::swprintf(time, 32, L"-- ms");
    else std::swprintf(time, 32, L"%.1f ms", static_cast<double>(ms));
    const float time_w = measure(time, *time_font).Width;
    say(*g, time, *time_font, tone::kSecondary, PointF(right - time_w, top + m.number_h * 0.86f));
    // The words' zone: the glass's inside, as dark as the quiet grey needs.
    look.zones = {Look::Zone{glass.X + m.pad_x / 2, glass.Y + m.pad_y / 2, glass.X + glass.Width - m.pad_x / 2, glass.Y + glass.Height - m.pad_y / 2,
                             kUnderSecondary}};
    look.feather = fpx(6);
    ++p.look_serial;
}

// ---- the bar's look (the painter's)

// The full screen chip's icon centred at (cx, cy): four corner brackets, their corners out (to full screen) or in (back
// to a window, when `full`), each arm on whole pixels for the pen's width (crisp).
void screen_icon(Graphics& g, Pen& line, float cx, float cy, bool full) {
    // The brackets' reach from the centre and the length of each arm, in whole pixels.
    const float outer = std::round(fpx(8)), inner = std::round(fpx(3)), arm = std::round(fpx(4.5f));
    const float width = line.GetWidth();
    for (int sx : {-1, 1}) {
        for (int sy : {-1, 1}) {
            // Out: the corner at the outer point, the arms going back in; in: the corner near the centre, the arms
            // going out, as the corners of a smaller square pushed in.
            const float corner = full ? inner : outer;
            const float back = full ? arm : -arm;
            const float x = crisp(cx + static_cast<float>(sx) * corner, width), y = crisp(cy + static_cast<float>(sy) * corner, width);
            const PointF bracket[] = {PointF(x, y + static_cast<float>(sy) * back), PointF(x, y), PointF(x + static_cast<float>(sx) * back, y)};
            g.DrawLines(&line, bracket, 3);
        }
    }
}

// An X centred at (cx, cy), `half` from its centre to each end.
void cross(Graphics& g, Pen& line, float cx, float cy, float half) {
    g.DrawLine(&line, cx - half, cy - half, cx + half, cy + half);
    g.DrawLine(&line, cx - half, cy + half, cx + half, cy - half);
}

// The minimise chip's glyph centred at (cx, cy): a short bar across, 14 long at 720 lines, on whole pixels for the pen's
// width (crisp).
void minimise_icon(Graphics& g, Pen& line, float cx, float cy) {
    const float half = std::round(fpx(7)), y = crisp(cy, line.GetWidth());
    g.DrawLine(&line, cx - half, y, cx + half, y);
}

// The bar's name: the OpenDMTQ wordmark as the launcher's header draws it (OPEN over its lime line, DMTQ in chrome with
// the Q lit; its pictures beside the player, overlay_glass.h's wordmark), 22 in from the bar's left end at 720 lines,
// as far as the X from its right end (overlay_scale.h's kBarEnds), and centred in its height as the header centres its
// own; drawn down with GDI+'s finest filter from the picture of the next larger scale when there is none of this one.
// Where the pictures are not there, "OPEN DMTQ" in the launcher's wordmark face, spaced out as its header spaces OPEN.
// Where it went, for its zone.
RectF bar_name(Graphics& g, float h) {
    float drawn_for = 0;
    if (Bitmap* mark = wordmark(scale(), drawn_for)) {
        const float k = scale() / drawn_for;
        const auto pw = static_cast<float>(mark->GetWidth()), ph = static_cast<float>(mark->GetHeight());
        // At its own size, on whole pixels: the picture's pixels as they are, nothing filtered.
        const bool own = std::fabs(k - 1.0f) < 0.001f;
        float x0 = wordmark_left(scale()), y = (h - ph * k) / 2;
        if (own) {
            x0 = std::round(x0);
            y = std::round(y);
        }
        const InterpolationMode before = g.GetInterpolationMode();
        g.SetInterpolationMode(own ? InterpolationModeNearestNeighbor : InterpolationModeHighQualityBicubic);
        // The picture's edge repeated past it as the filter reads beyond it (no dark fringe at the mark's sides).
        ImageAttributes edges;
        edges.SetWrapMode(WrapModeTileFlipXY);
        g.DrawImage(mark, RectF(x0, y, pw * k, ph * k), 0, 0, pw, ph, UnitPixel, &edges);
        g.SetInterpolationMode(before);
        return RectF(x0, y, pw * k, ph * k);
    }
    const std::wstring name = L"OPEN DMTQ";
    // 0.2 em after each letter.
    const float size = fpx(15);
    const float spacing = size * 0.2f;
    auto f = wide_font(size);
    const float line = measure(L"O", *f).Height;
    const float x0 = wordmark_left(scale()), y = (h - line) / 2;
    float x = x0;
    for (std::size_t i = 0; i < name.size(); ++i) {
        const std::wstring letter(1, name[i]);
        say(g, letter, *f, tone::kPrimary, PointF(x, y));
        x += measure(letter, *f).Width + (i + 1 < name.size() ? spacing : 0.0f);
    }
    return RectF(x0, y, x - x0, line);
}

// The bar's look for the chip under the pointer, the one held, and full screen or not (its chip's icon the other way),
// across the view's whole width.
void bar_look(Paint& p, int hover, int pressed, bool full) {
    const int w = area_w();
    Look& look = p.look;
    const int h = bar_height();
    const int win_h = h + px(kRoomBottom);
    // Glass across the game's whole width, square, from its very top: its shape goes past the window's sides and top,
    // so that its shadow falls evenly under it (made again only for a new size: shape() keeps what it made).
    pane_shape(look, w, win_h, RectF(-1000, -1000, static_cast<REAL>(w + 2000), static_cast<REAL>(h + 1000)), 0, true);
    look.top = 0;
    look.height = static_cast<float>(h);
    look.tint = kTintPiece;
    p.x = 0;
    p.y = 0;
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(look, surface));
    // The game's bevel along its top (a faint line of light), then its green line along its foot, its one edge in sight
    // (the others are the game's own), fading out toward both ends as the line under the game's tab row does.
    {
        const float line = std::max(1.0f, fpx(1));
        SolidBrush light(Color(30, 255, 255, 255));
        g->FillRectangle(&light, 0.0f, 0.0f, static_cast<REAL>(w), line);
        SolidBrush shade(Color(70, 0, 0, 0));
        g->FillRectangle(&shade, 0.0f, static_cast<REAL>(h) - 2 * line, static_cast<REAL>(w), line);
        game_line(*g, 0, static_cast<float>(w), static_cast<float>(h) - line, game::kLine);
    }
    // The name on the left, in the wordmark's face.
    const RectF name = bar_name(*g, static_cast<float>(h));
#ifdef OVERLAY_TEST_HOOKS
    // Where it went, for the probe.
    g_test_bar_name = name;
#endif
    // The chips as the launcher's buttons (cut at two corners, raised, sunk while held): the X its main button, in the
    // lime from the start with a dark X, so that it stands out the moment the bar shows, a little brighter under the
    // pointer; full screen and minimise its secondary buttons, quiet metal, a lighter plate under the pointer, no lime.
    // Their glyphs bolder than the words' lines (2.5 at 720 lines, in whole pixels so that they stay crisp).
    g->Flush(FlushIntentionSync);
    for (int which : {kQuitChip, kScreenChip, kMinChip}) {
        const RectF r = chip_rect(which, w);
        const bool quit = which == kQuitChip;
        const bool lit = which == hover, in = lit && which == pressed;
        const Fill& fill = quit ? (in ? launcher::kMainPressed : lit ? launcher::kMainHover : launcher::kMain)
                                : (in ? launcher::kMetalPressed : lit ? launcher::kMetalHover : launcher::kMetal);
        launcher_face(*look.fore, static_cast<int>(r.X), static_cast<int>(r.Y), static_cast<int>(r.Width), static_cast<int>(r.Height), fill, in, scale());
    }
    const float stroke = std::max(2.0f, std::round(fpx(2.5f)));
    for (int which : {kQuitChip, kScreenChip, kMinChip}) {
        const RectF r = chip_rect(which, w);
        const bool quit = which == kQuitChip;
        Pen line_pen(quit ? launcher::kMainInk : launcher::kMetalInk, stroke);
        line_pen.SetLineJoin(LineJoinMiter);
        const float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2;
        if (quit) {
            line_pen.SetStartCap(LineCapRound);
            line_pen.SetEndCap(LineCapRound);
            cross(*g, line_pen, cx, cy, fpx(6.5f));
        } else if (which == kScreenChip) {
            screen_icon(*g, line_pen, cx, cy, full);
        } else {
            minimise_icon(*g, line_pen, cx, cy);
        }
    }
    // The name's zone: the tint deepens there as much as the frame behind needs for it.
    look.zones = {Look::Zone{name.X - fpx(6), name.Y - fpx(4), name.X + name.Width + fpx(6), name.Y + name.Height + fpx(4), kUnderPrimary}};
    look.feather = fpx(28);
    ++p.look_serial;
}

// ---- the question's look (its layout both threads', its picture the painter's)

// The question's choices and what the mouse may be on: a button, the thin X, beside the card.
constexpr int kKeep = 0, kQuit = 1, kClose = 2, kBeside = 3;

// The question's layout in the game's area: the card in the middle, its title and the line under it, its thin X, its
// two buttons.
struct AskLayout {
    RectF card, title, text, close, keep, quit;
    // The game's line under the title: from x0 to x1 at row y.
    float line_x0 = 0, line_x1 = 0, line_y = 0;
};
AskLayout ask_layout() {
    // Within the game's area whatever the scale (AskScale's cap, a guard).
    const AskScale cap;
    AskLayout l;
    const float w = static_cast<float>(area_w()), h = static_cast<float>(area_h());
    const float width = fpx(kCardWidth), height = fpx(kCardHeight);
    l.card = RectF(std::floor((w - width) / 2), std::floor((h - height) / 2), static_cast<REAL>(px(kCardWidth)), static_cast<REAL>(px(kCardHeight)));
    const float x = l.card.X, y = l.card.Y, cw = l.card.Width;
    // At 720 lines: the title centred 36 from the top, 28 high; the game's line 10 under it (300 wide, fading to its
    // ends); the line of words 12 under that, 20 high; the buttons, 210 by 48 side by side with 16 between, centred 34
    // under them; 40 under the buttons.
    l.title = RectF(x + fpx(56), y + fpx(36), cw - fpx(112), fpx(28));
    l.line_x0 = x + (cw - fpx(300)) / 2;
    l.line_x1 = l.line_x0 + fpx(300);
    l.line_y = y + fpx(74);
    l.text = RectF(x + fpx(28), y + fpx(86), cw - fpx(56), fpx(20));
    // The thin X's square at the card's right, 40 to press with the glyph in its middle, on the title's middle: the
    // two read as one row.
    l.close = RectF(x + cw - fpx(52), l.title.Y + l.title.Height / 2 - fpx(20), fpx(40), fpx(40));
    const float each = static_cast<float>(px(210)), tall = static_cast<float>(px(48)), gap = static_cast<float>(px(16));
    l.keep = RectF(std::floor(x + (cw - each * 2 - gap) / 2), std::floor(y + fpx(140)), each, tall);
    l.quit = RectF(l.keep.X + each + gap, l.keep.Y, each, tall);
    return l;
}

// The question's words in the language of the PC.
const wchar_t* ask_title() { return g_korean ? L"게임을 끝낼까요?" : L"Quit the game?"; }
// What quitting loses, true on any screen: the player cannot tell whether a song is going on.
const wchar_t* ask_text() { return g_korean ? L"곡 도중에 끝내면 기록이 남지 않아요." : L"Quitting mid-song loses the song's record."; }
const wchar_t* keep_label() { return g_korean ? L"계속하기" : L"Keep playing"; }
const wchar_t* quit_label() { return g_korean ? L"게임 끝내기" : L"Quit the game"; }

// The card's look for the keys' choice, what is under the pointer and what is held, in a window around the card: glass
// with the game's corners (6) and bevel, its title bold and centred with the game's green line under it, its line
// regular; its buttons the launcher's, as its dialogs draw them: Keep playing its main button (the lime, dark words),
// Quit the game its secondary (quiet metal, chalk words) that fills red under the pointer as its buttons that remove do
// (dark words then), each sunk while held, the keys' choice in its keyboard ring; the thin X a plain glyph, ash and white
// under the pointer, as the launcher's menu names.
void card_look(Look& card_look_out, const AskLayout& l, int choice, int hover, int pressed) {
    const AskScale cap;
    // The card's window: the card with its shadow's room, within the game's area.
    const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
    const int w = win.right - win.left, h = win.bottom - win.top;
    const float ox = static_cast<float>(win.left), oy = static_cast<float>(win.top);
    auto at = [&](RectF r) { return RectF(r.X - ox, r.Y - oy, r.Width, r.Height); };
    const float radius = fpx(6);
    const RectF card = at(l.card);
    Look& look = card_look_out;
    pane_shape(look, w, h, card, radius);
    look.tint = kTintCard;
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(look, surface));
    edge(*g, card, radius);
    bevel(*g, card, radius, 40, 90);
    // The game's green line under the title, fading out toward its ends.
    game_line(*g, l.line_x0 - ox, l.line_x1 - ox, l.line_y - oy, game::kLine);
    // The title, bold, and the quiet line under it, regular, both centred.
    auto title_font = font(Weight::kBold, fpx(19), g_korean);
    auto text_font = font(Weight::kRegular, fpx(15), g_korean);
    say_centred(*g, ask_title(), *title_font, tone::kPrimary, at(l.title));
    say_centred(*g, ask_text(), *text_font, tone::kSecondary, at(l.text));
    // The thin X: the launcher's ash (#AEB8C3), white under the pointer.
    const RectF close = at(l.close);
    Pen thin(hover == kClose ? Color(255, 255, 255, 255) : Color(255, 0xAE, 0xB8, 0xC3), fpx(1.5f));
    thin.SetStartCap(LineCapRound);
    thin.SetEndCap(LineCapRound);
    cross(*g, thin, close.X + close.Width / 2, close.Y + close.Height / 2, fpx(7));
    // The two buttons; under the pointer each lights (Quit the game red), held each is sunk; the keys' choice ringed.
    const bool keep_lit = hover == kKeep, quit_lit = hover == kQuit;
    const bool keep_in = keep_lit && pressed == kKeep, quit_in = quit_lit && pressed == kQuit;
    const RectF keep = at(l.keep), quit = at(l.quit);
    g->Flush(FlushIntentionSync);
    auto face_at = [&](const RectF& r, const Fill& fill, bool in) {
        launcher_face(*look.fore, static_cast<int>(r.X), static_cast<int>(r.Y), static_cast<int>(r.Width), static_cast<int>(r.Height), fill, in, scale());
    };
    face_at(keep, keep_in ? launcher::kMainPressed : keep_lit ? launcher::kMainHover : launcher::kMain, keep_in);
    face_at(quit, quit_in ? launcher::kRedPressed : quit_lit ? launcher::kRed : launcher::kMetal, quit_in);
    const RectF& ringed = choice == kQuit ? quit : keep;
    launcher_ring(*look.fore, static_cast<int>(ringed.X), static_cast<int>(ringed.Y), static_cast<int>(ringed.Width), static_cast<int>(ringed.Height), scale());
    auto label = font(Weight::kBold, fpx(16), g_korean);
    say_centred(*g, keep_label(), *label, launcher::kMainInk, keep);
    say_centred(*g, quit_label(), *label, quit_lit ? launcher::kRedInk : launcher::kMetalInk, quit);
    // The words' zone: the title and the line, as dark as the quiet line needs (the buttons are solid).
    const RectF title = at(l.title), text = at(l.text);
    look.zones = {Look::Zone{text.X - fpx(4), title.Y - fpx(4), text.X + text.Width + fpx(4), text.Y + text.Height + fpx(4), kUnderSecondary}};
    look.feather = fpx(20);
}

// What is under a point of the question's window: a button, the thin X, or kNone.
int ask_at(int x, int y) {
    const AskLayout l = ask_layout();
    const auto fx = static_cast<REAL>(x), fy = static_cast<REAL>(y);
    if (l.keep.Contains(fx, fy)) return kKeep;
    if (l.quit.Contains(fx, fy)) return kQuit;
    if (l.close.Contains(fx, fy)) return kClose;
    return kNone;
}
bool in_card(int x, int y) { return ask_layout().card.Contains(static_cast<REAL>(x), static_cast<REAL>(y)); }

// ---- the notice's look (the painter's)

// The notice's look for "title\ndetail": a glass card with the red LIVE tag on its left while live (once ended, the
// title says so alone: no tag), the title over where to watch; its window's place goes to the paint, centred at the top
// of the game's area, clear of a counter in a top corner (`corner`, Settings::ShowFps's order).
void notice_look(Paint& p, const std::string& text, bool live, int corner) {
    const std::wstring all = wide(text);
    const std::size_t cut = all.find(L'\n');
    std::wstring title = all.substr(0, cut), detail = cut == std::wstring::npos ? L"" : all.substr(cut + 1);
    auto title_font = font(Weight::kBold, fpx(16), g_korean);
    auto detail_font = font(Weight::kRegular, fpx(13), g_korean);
    auto badge_font = font(Weight::kBold, fpx(11), g_korean);
    const std::wstring badge = L"LIVE";
    // The room inside the card: to the tag, between it and the words, after the words; the tag's own, the game's tag
    // (as its MY RANK), whose slanted right end takes a little more room. No tag once ended: the words start at the pad.
    const float pad = fpx(16), gap = live ? fpx(12) : 0.0f, after = fpx(20), badge_h = fpx(22), badge_pad = fpx(9);
    const float slant = badge_h * 0.36f;
    const float badge_w = live ? measure(badge, *badge_font).Width + badge_pad * 2 + fpx(0.66f) * 4 + slant : 0.0f;
    // The words' room: within 560 at 720 lines, and within the game's area however small its window; a long server name
    // wraps there, into even lines. A counter in a top corner keeps its corner: the card, centred, stays clear of it.
    const int aw = area_w();
    float beside = pad + badge_w + gap + after + 2 * px(kRoomSide);
    if (corner == 1 || corner == 2) {
        // The counter's size and place as it is drawn, at its own scale; the notice's own lengths at the overlay's.
        FpsMetrics m{};
        POINT at{};
        {
            const CounterScale own;
            m = fps_metrics();
            at = fps_place(corner, static_cast<int>(m.w), static_cast<int>(m.h));
        }
        // How far in from its side the counter reaches, on both sides, with a gap.
        const float reach = corner == 1 ? static_cast<float>(at.x) + m.w : static_cast<float>(aw - at.x);
        beside = std::max(beside, pad + badge_w + gap + after + 2.0f * (reach + fpx(8)));
    }
    const float room = std::max(fpx(160), std::min(fpx(560) - pad - badge_w - gap - after, static_cast<float>(aw) - beside));
    std::vector<std::wstring> title_lines = wrap_even(title, *title_font, room);
    std::vector<std::wstring> detail_lines = detail.empty() ? std::vector<std::wstring>{} : wrap_even(detail, *detail_font, room);
    float text_w = 0;
    for (const auto& line : title_lines) text_w = std::max(text_w, measure(line, *title_font).Width);
    for (const auto& line : detail_lines) text_w = std::max(text_w, measure(line, *detail_font).Width);
    const float title_line = measure(L"Ag", *title_font).Height, detail_line = measure(L"Ag", *detail_font).Height;
    const float line_gap = fpx(2);
    const float text_h = title_line * static_cast<float>(title_lines.size()) + (detail_lines.empty() ? 0 : line_gap + detail_line * static_cast<float>(detail_lines.size()));
    // The glass: about 64 high for a title and a line under it, a little more for wrapped lines.
    const float glass_w = std::ceil(pad + badge_w + gap + text_w + after);
    const float glass_h = std::ceil(std::max(fpx(64), text_h + fpx(24)));
    // Its place: centred at the top of the game's area, 16 down, under the bar while that is down.
    const int gx = (aw - static_cast<int>(glass_w)) / 2, gy = px(16) + top_room();
    const RECT win = window_around(gx, gy, static_cast<int>(glass_w), static_cast<int>(glass_h));
    p.x = win.left;
    p.y = win.top;
    Look& look = p.look;
    const int w = win.right - win.left, h = win.bottom - win.top;
    const RectF glass(static_cast<REAL>(gx - win.left), static_cast<REAL>(gy - win.top), glass_w, glass_h);
    const float radius = fpx(6);
    pane_shape(look, w, h, glass, radius);
    look.tint = kTintPiece;
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(look, surface));
    // The tag in the middle of the glass's height while live: the game's tag, nearly square on its left, its right end
    // slanted down to the left, Windows' close red, white bold words at 5:1 and more.
    const RectF tag(glass.X + pad, glass.Y + (glass_h - badge_h) / 2, badge_w, badge_h);
    GraphicsPath tag_path;
    {
        const float corner_r = fpx(2);
        tag_path.AddLine(tag.X + corner_r, tag.Y, tag.X + tag.Width, tag.Y);
        tag_path.AddLine(tag.X + tag.Width, tag.Y, tag.X + tag.Width - slant, tag.Y + tag.Height);
        tag_path.AddLine(tag.X + tag.Width - slant, tag.Y + tag.Height, tag.X + corner_r, tag.Y + tag.Height);
        tag_path.AddArc(tag.X, tag.Y + tag.Height - corner_r * 2, corner_r * 2, corner_r * 2, 90, 90);
        tag_path.AddArc(tag.X, tag.Y, corner_r * 2, corner_r * 2, 180, 90);
        tag_path.CloseFigure();
    }
    edge(*g, glass, radius);
    bevel(*g, glass, radius, 40, 90);
    // The game's green line along its foot while live, fading out toward both ends; none once the broadcast ended.
    if (live) game_line(*g, glass.X + radius, glass.X + glass.Width - radius, glass.Y + glass.Height - std::max(1.0f, fpx(1)), game::kLine);
    if (live) {
        LinearGradientBrush fill(PointF(0, tag.Y - 1), PointF(0, tag.Y + tag.Height + 1), game::kRedTop, game::kRedFoot);
        g->FillPath(&fill, &tag_path);
    }
    // Its word, spaced a little as a badge's is, white and bold, in the part left of its slant.
    if (live) {
        const float spacing = fpx(0.66f);
        const RectF word = measure(badge, *badge_font);
        float x = tag.X + (tag.Width - slant - word.Width - spacing * static_cast<float>(badge.size() - 1)) / 2;
        const float y = tag.Y + (tag.Height - word.Height) / 2;
        for (wchar_t ch : badge) {
            const std::wstring one(1, ch);
            say(*g, one, *badge_font, Color(255, 255, 255, 255), PointF(x, y));
            x += measure(one, *badge_font).Width + spacing;
        }
    }
    // The title, and where to watch under it, in the middle of the glass's height.
    const float tx = tag.X + badge_w + gap, ty = glass.Y + (glass_h - text_h) / 2;
    float y = ty;
    for (const auto& line : title_lines) {
        say(*g, line, *title_font, tone::kPrimary, PointF(tx, y));
        y += title_line;
    }
    y += line_gap;
    for (const auto& line : detail_lines) {
        say(*g, line, *detail_font, tone::kSecondary, PointF(tx, y));
        y += detail_line;
    }
    // The words' zone, as dark as the quiet line needs.
    look.zones = {Look::Zone{tx - fpx(4), ty - fpx(2), tx + text_w + fpx(4), ty + text_h + fpx(2), detail_lines.empty() ? kUnderPrimary : kUnderSecondary}};
    look.feather = fpx(14);
    ++p.look_serial;
}

// ---- the handle's look (the painter's)

// A picture worked out a pixel at a time: each pixel's colour and opacity as floats, premultiplied, so that parts laid
// over one another keep their own colours where they meet (the green line is the same green on the glass as beside it).
struct Layers {
    int w, h;
    std::vector<float> r, g, b, a;
    Layers(int width, int height)
        : w(width), h(height), r(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), 0.0f), g(r), b(r), a(r) {}
    // A part laid over what is there: `mask` its share of each pixel, in the colour (0 to 255 each) at `strength`.
    void lay(const std::vector<float>& mask, float red, float green, float blue, float strength) {
        for (std::size_t i = 0; i < mask.size(); ++i) {
            const float part = std::clamp(mask[i] * strength, 0.0f, 1.0f);
            // Nothing of it on this pixel.
            if (part <= 0.0f) continue;
            // The part over what was there, as one sheet of colour over another.
            r[i] = red * part + r[i] * (1.0f - part);
            g[i] = green * part + g[i] * (1.0f - part);
            b[i] = blue * part + b[i] * (1.0f - part);
            a[i] = part + a[i] * (1.0f - part);
        }
    }
    void lay(const std::vector<float>& mask, const Color& colour, float strength) {
        lay(mask, static_cast<float>(colour.GetR()), static_cast<float>(colour.GetG()), static_cast<float>(colour.GetB()), strength);
    }
    // The whole of it into a window's picture, as bytes: premultiplied, as the window takes them.
    void into(Canvas& c) const {
        auto* px = static_cast<std::uint32_t*>(c.bits);
        const auto byte = [](float v) { return static_cast<std::uint32_t>(std::lround(std::clamp(v, 0.0f, 255.0f))); };
        for (std::size_t i = 0; i < a.size(); ++i) px[i] = byte(a[i] * 255.0f) << 24 | byte(r[i]) << 16 | byte(g[i]) << 8 | byte(b[i]);
    }
};

// A convex outline's sides each moved in by `by` (its corners in order): each new corner where two moved sides meet.
std::vector<PointF> moved_in(const std::vector<PointF>& p, float by) {
    if (by <= 0.0f) return p;
    const std::size_t n = p.size();
    // Which way the outline turns (the sign of its area): that says which side of a side is the inside.
    float area = 0.0f;
    for (std::size_t i = 0; i < n; ++i) area += p[i].X * p[(i + 1) % n].Y - p[(i + 1) % n].X * p[i].Y;
    const float turn = area > 0.0f ? 1.0f : -1.0f;
    // Each side as a point on it, moved in, and its direction.
    struct Side {
        float x, y, dx, dy;
    };
    std::vector<Side> sides;
    for (std::size_t i = 0; i < n; ++i) {
        const PointF from = p[i], to = p[(i + 1) % n];
        float dx = to.X - from.X, dy = to.Y - from.Y;
        const float length = std::sqrt(dx * dx + dy * dy);
        dx /= length;
        dy /= length;
        // Moved along its normal toward the inside.
        sides.push_back(Side{from.X - dy * turn * by, from.Y + dx * turn * by, dx, dy});
    }
    std::vector<PointF> out;
    for (std::size_t i = 0; i < n; ++i) {
        // The corner between the side before and this one: where their lines cross.
        const Side& before = sides[(i + n - 1) % n];
        const Side& here = sides[i];
        const float cross = before.dx * here.dy - before.dy * here.dx;
        // Two sides in one line have no crossing: the moved point itself.
        if (std::fabs(cross) < 1e-6f) {
            out.push_back(PointF(here.x, here.y));
            continue;
        }
        const float along = ((here.x - before.x) * here.dy - (here.y - before.y) * here.dx) / cross;
        out.push_back(PointF(before.x + before.dx * along, before.y + before.dy * along));
    }
    return out;
}

// A convex outline with its corners rounded by `radius`, the whole of it shrunk by `shrunk` on every side, as each
// pixel's share of it: the outline's sides moved in by the larger of the two, and a round pen as wide as what is left
// of the radius drawn around that.
std::vector<float> rounded_outline(int w, int h, const std::vector<PointF>& p, float radius, float shrunk) {
    const float in = std::max(radius, shrunk), round = in - shrunk;
    const std::vector<PointF> core = moved_in(p, in);
    return coverage(w, h, [&](Graphics& g) {
        SolidBrush white(Color(255, 255, 255, 255));
        g.FillPolygon(&white, core.data(), static_cast<INT>(core.size()));
        // No radius left: its corners are sharp.
        if (round <= 0.01f) return;
        Pen pen(Color(255, 255, 255, 255), round * 2);
        pen.SetLineJoin(LineJoinRound);
        g.DrawPolygon(&pen, core.data(), static_cast<INT>(core.size()));
    });
}

// The handle, as picked from thirty drawn over the game's frames at its real sizes: the game's green line along its top
// edge at the centre (the rail: the bar's own foot line, a short piece of it in sight), fading out toward its ends, and
// a small tab of charcoal glass hanging from it, its sides leaning in as the game's own tabs' do and the line going on
// around it as its outline; in the tab a white chevron pointing down, which says that a bar comes down from here. With
// the pointer on it (`lit`) the line, the outline and the chevron are the lime, the rail longer and the tab deeper, its
// chevron lower, as if pulled. As large as the game's header leaves room for at its top centre, at the game's own
// scale: it covers none of the game's words or buttons on any of its screens. No glass is read for it: its charcoal
// lies straight on the game. Its picture is the handle's window at rest, its place in the game's area in x and y; `lip`
// the rows of its rail and the shade under it, which the bar's foot takes the place of as the bar comes down.
std::shared_ptr<Canvas> handle_picture(int& x, int& y, int& lip, bool lit) {
    const float k = handle_scale();
    const float rail_w = hpx(lit ? kRailWideLit : kRailWide), top_w = hpx(kTabTop), tall = hpx(lit ? kTabTallLit : kTabTall);
    // The window: the rail's width (the widest part) and the tab's height, with room for their smooth edges; as even or
    // odd across as the game's area, so that the tab's middle is the area's middle exactly.
    const int w = static_cast<int>(std::ceil(std::max(rail_w, top_w) / 2 + kHandleRoom)) * 2 + area_w() % 2;
    const int h = static_cast<int>(std::ceil(tall + kHandleRoom));
    x = (area_w() - w) / 2;
    y = 0;
    // The lines' widths in whole pixels, so that they stay crisp: the rail, the shade under it (overlay_scale.h's
    // rows, which a check holds within the header's rows above its buttons), the tab's outline.
    const float rail_h = static_cast<float>(rail_rows(k)), shade_h = static_cast<float>(shade_rows(k));
    const float edge = std::max(1.0f, std::round(hpx(kTabEdge)));
    lip = static_cast<int>(rail_h + shade_h);
    auto c = std::make_shared<Canvas>(w, h);
    if (!c->bits) return c;
    const float cx = static_cast<float>(area_w()) / 2 - static_cast<float>(x);
    Layers picture(w, h);
    // The tab's outline: from well above the window (so that it meets the game's edge square) down its leaning sides to
    // its foot.
    const float above = 20 * k;
    const auto half = [&](float depth) { return top_w / 2 - depth * kTabLean; };
    const std::vector<PointF> tab = {PointF(cx - half(-above), -above), PointF(cx + half(-above), -above), PointF(cx + half(tall), tall),
                                     PointF(cx - half(tall), tall)};
    const float radius = hpx(kTabRound);
    const std::vector<float> glass = rounded_outline(w, h, tab, radius, 0);
    // The glass: the overlay's charcoal, then a little light at its top that is gone by its foot.
    picture.lay(glass, static_cast<float>(kTintR), static_cast<float>(kTintG), static_cast<float>(kTintB), kTabGlass);
    {
        std::vector<float> sheen = glass;
        for (int row = 0; row < h; ++row) {
            const float light = std::max(0.0f, 1.0f - static_cast<float>(row) / std::max(1.0f, tall));
            for (int col = 0; col < w; ++col) sheen[static_cast<std::size_t>(row) * static_cast<std::size_t>(w) + static_cast<std::size_t>(col)] *= light;
        }
        picture.lay(sheen, 255, 255, 255, kTabSheen);
    }
    // The line's colour and strength: the game's green at rest, its lime, whole, with the pointer on it.
    const Color& line = lit ? tone::kLime : game::kLine;
    const float line_alpha = lit ? 1.0f : kHandleLine;
    // The outline: what the glass has that the same shape shrunk by the outline's width has not.
    {
        const std::vector<float> inside = rounded_outline(w, h, tab, radius, edge);
        std::vector<float> outline(glass.size());
        for (std::size_t i = 0; i < outline.size(); ++i) outline[i] = std::max(0.0f, glass[i] - inside[i]);
        picture.lay(outline, line, line_alpha);
    }
    // The rail along the game's top edge, either side of the tab (it stops just inside the tab's top corners, where the
    // outline takes over), whole in its middle and fading out toward both ends; a line of shade under it, which keeps
    // it seen on a white picture.
    {
        std::vector<float> rail(glass.size(), 0.0f), shade(glass.size(), 0.0f);
        const float gap = top_w - hpx(1.6f);
        for (int row = 0; row < h && static_cast<float>(row) < rail_h + shade_h; ++row) {
            for (int col = 0; col < w; ++col) {
                // The pixel's middle, from the rail's left end.
                const float at = static_cast<float>(col) + 0.5f - (cx - rail_w / 2);
                if (at < 0.0f || at > rail_w || std::fabs(at - rail_w / 2) < gap / 2) continue;
                const float along = at / rail_w;
                const float whole = std::min({1.0f, along / kRailFade, (1.0f - along) / kRailFade});
                (static_cast<float>(row) < rail_h ? rail : shade)[static_cast<std::size_t>(row) * static_cast<std::size_t>(w) + static_cast<std::size_t>(col)] = whole;
            }
        }
        picture.lay(shade, 0, 0, 0, kRailShadeAlpha);
        picture.lay(rail, line, line_alpha);
    }
    // The chevron: two strokes meeting at its point, round at their ends and where they meet.
    {
        const float wide = hpx(kChevWide), deep = hpx(kChevDeep), top = hpx(lit ? kChevTopLit : kChevTop);
        const std::vector<float> chevron = coverage(w, h, [&](Graphics& g) {
            Pen pen(Color(255, 255, 255, 255), std::max(1.0f, hpx(kChevStroke)));
            pen.SetLineJoin(LineJoinRound);
            pen.SetStartCap(LineCapRound);
            pen.SetEndCap(LineCapRound);
            const PointF arms[] = {PointF(cx - wide / 2, top), PointF(cx, top + deep), PointF(cx + wide / 2, top)};
            g.DrawLines(&pen, arms, 3);
        });
        picture.lay(chevron, lit ? tone::kLime : tone::kPrimary, lit ? 1.0f : kChevAlpha);
    }
    picture.into(*c);
    return c;
}

// ---- the painter: its orders and what it hands back

// The pieces, in the order the painter takes their orders: the question first (the game waits for it to be held).
enum Piece { kQuestionPiece, kBarPiece, kNoticePiece, kCounterPiece, kHandlePiece, kPieces };

// What one piece is to show, as the UI thread asks for it: the view it is drawn for, the frame's last read, and each
// piece's own state (the rest left as it is).
struct Order {
    bool wanted = false;
    View view;
    std::shared_ptr<const std::vector<glass::Shot>> shots;
    // The bar's chip under the pointer and the one held; the question's choice, what is under its pointer and held.
    int hover = kNone, pressed = kNone, choice = kKeep;
    // The notice's words and whether it is live; the counter's corner and its numbers; whether the handle is lit.
    std::string text;
    bool live = false, lit = false;
    int corner = 0, fps = -1;
    float ms = 0;
    // The notice's picture where it lies under the question's dim (null: none up), and its place in the game's area.
    std::shared_ptr<Canvas> under;
    int under_x = 0, under_y = 0;
    // The look as text, which the picture handed back carries: the UI thread knows which look it got.
    std::string key;
};

// A picture made: what it shows (its order's key), its window's place in the game's area, whether the frame was behind
// it, and its number.
struct Painted {
    bool ready = false;
    std::shared_ptr<Canvas> picture;
    int x = 0, y = 0;
    bool glass = false;
    unsigned made = 0;
    std::string key;
    // The rows at the picture's top that its motion counts by: the bar's own height above its shadow, the handle's
    // rail (0 for the others).
    int rows = 0;
    // The room the bar took at the game's top in the view its place was worked out for: a piece that moves under the
    // bar is shown lower or higher by what the bar shows more or less than that.
    int room = 0;
};

// The orders waiting and the pictures made, one of each a piece (a newer order takes an older one's place), under the
// lock; the painter waits on `g_paint_wake`; the question's pictures let go of when it closes.
std::mutex g_paint_lock;
std::condition_variable g_paint_wake;
Order g_orders[kPieces];
Painted g_painted[kPieces];
bool g_drop_question = false;
// The window the painter tells of a picture made (the overlay's clock), and the message it posts.
HWND g_clock = nullptr;
constexpr UINT kPaintedMessage = WM_APP + 1;
// What the painter's pictures cost it, for the stats line: pictures made and their time, the longest.
std::atomic<std::uint64_t> g_paint_count{0}, g_paint_ns{0}, g_paint_most_ns{0};

// The steady clock in nanoseconds.
std::int64_t now_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }

// The question's pictures as the painter keeps them: the dimmed game behind the card (opaque, the area's size), the
// card's glass and the frame behind it, and the whole picture (the dim and the card over it), with what they were made
// from.
struct QuestionPaint {
    std::unique_ptr<Canvas> dim;
    std::uint64_t dim_hash = 1;
    std::string dim_for;
    Look card;
    Backdrop card_backdrop;
    bool card_have = false;
    std::shared_ptr<Canvas> picture, spare;
    std::string drawn_for;
    unsigned made = 0;
};

// The bar's picture for an order, whole, at its place when it is down (the UI thread shows the part of it in sight).
Painted paint_bar(const Order& o, Paint& p) {
    const Drawing d(o.view);
    if (p.made_for != o.key) {
        bar_look(p, o.hover, o.pressed, o.view.full);
        p.made_for = o.key;
    }
    paint_draw(p, *o.shots);
    Painted made{true, p.picture, p.x, p.y, p.have_backdrop, p.made, o.key};
    // Its own rows above its shadow, at this view's scale: what its slide counts by.
    made.rows = bar_height();
    return made;
}

// The notice's picture for an order, at its resting place (the UI thread slides its window).
Painted paint_notice(const Order& o, Paint& p) {
    const Drawing d(o.view);
    if (p.made_for != o.key) {
        notice_look(p, o.text, o.live, o.corner);
        p.made_for = o.key;
    }
    paint_draw(p, *o.shots);
    Painted made{true, p.picture, p.x, p.y, p.have_backdrop, p.made, o.key};
    // Placed under the room the bar took in this view.
    made.room = o.view.top_room;
    return made;
}

// The counter's picture for an order, at its own scale: its look, and its glass's blur over the frame behind.
Painted paint_counter(const Order& o, Paint& p) {
    const Drawing d(o.view);
    const CounterScale own;
    if (p.made_for != o.key) {
        fps_look(p, o.fps, o.ms, o.corner);
        p.made_for = o.key;
    }
    paint_draw(p, *o.shots);
    Painted made{true, p.picture, p.x, p.y, p.have_backdrop, p.made, o.key};
    // In a top corner it is placed under the room the bar took in this view; at the bottom the bar never moves it.
    made.room = o.corner == 1 || o.corner == 2 ? o.view.top_room : 0;
    return made;
}

// The handle's picture for an order: made again only for another view, or with the pointer come on it or gone.
Painted paint_handle(const Order& o, Paint& p) {
    const Drawing d(o.view);
    if (p.made_for != o.key || !p.picture) {
        p.picture = handle_picture(p.x, p.y, p.lip, o.lit);
        p.made = ++g_made;
        p.made_for = o.key;
    }
    Painted made{true, p.picture, p.x, p.y, false, p.made, o.key};
    // Its rail's rows, which the bar's foot takes the place of as the bar comes down.
    made.rows = p.lip;
    return made;
}

// The question's picture for an order: the dimmed, blurred game from a read of the whole frame (the notice laid over it,
// as it lies under the dim), made again only when that read changed, and the card over it; the bare dim without one.
Painted paint_question(const Order& o, QuestionPaint& q) {
    const Drawing d(o.view);
    const int w = area_w(), h = area_h();
    const AskScale cap;
    // The dim: made again for another read, another size or another notice under it.
    Backdrop whole;
    const bool have = backdrop_from(*o.shots, glass::Rect{0, 0, w, h}, 0, whole);
    char dim_for[96];
    std::snprintf(dim_for, sizeof dim_for, "%dx%d %.4f %llx %p %d,%d", w, h, static_cast<double>(scale()), static_cast<unsigned long long>(have ? whole.hash : 0),
                  static_cast<void*>(o.under.get()), o.under_x, o.under_y);
    if (!q.dim || q.dim_for != dim_for) {
        q.dim_for = dim_for;
        if (!q.dim || q.dim->w != w || q.dim->h != h) q.dim = std::make_unique<Canvas>(w, h);
        if (have) {
            // The notice under the dim, as the screen shows it now.
            if (o.under) stamp(whole, *o.under, o.under_x, o.under_y);
            // The card's own frame: the dim's, blurred on to the card's blur (their blurs add as squares) and pushed out.
            q.card_backdrop = whole;
            soften(q.card_backdrop, std::sqrt(fpx(kDimBlur) * fpx(kDimBlur) + fpx(kGlassBlur) * fpx(kGlassBlur)), kGlassSaturation, kDim);
            q.card_have = true;
            soften(whole, fpx(kDimBlur), 1.0f, kDim);
        } else {
            q.card_have = false;
        }
        // Without a frame, a deeper plain dim: the game shows through it unblurred.
        if (q.dim->bits) backdrop_fill(*q.dim, have ? &whole : nullptr, 0.6f);
        // The whole picture made again over the new dim.
        q.drawn_for.clear();
    }
    // The same look over the same dim at the same size: the picture made last.
    const std::string drawn_for = o.key + " " + q.dim_for;
    if (q.picture && q.drawn_for == drawn_for) return Painted{true, q.picture, 0, 0, q.card_have, q.made, o.key};
    std::shared_ptr<Canvas> c = free_canvas(q.spare, w, h);
    if (!c->bits || !q.dim || !q.dim->bits) return Painted{};
    // The dim, then the card over it, in its window.
    std::memcpy(c->bits, q.dim->bits, static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 4);
    const AskLayout l = ask_layout();
    card_look(q.card, l, o.choice, o.hover, o.pressed);
    const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
    compose(*c, win.left, win.top, q.card, q.card_have ? &q.card_backdrop : nullptr, win.left, win.top);
    q.spare = std::move(q.picture);
    q.picture = std::move(c);
    q.made = ++g_made;
    q.drawn_for = drawn_for;
    return Painted{true, q.picture, 0, 0, q.card_have, q.made, o.key};
}

// The painter's thread: each order as it comes (the newest of each piece), its picture handed back, the UI thread told.
void painter_loop() {
    // Its own state, which no other thread touches.
    Paint paints[kPieces];
    QuestionPaint question;
    for (;;) {
        Order mine[kPieces];
        bool drop = false;
        {
            std::unique_lock<std::mutex> l(g_paint_lock);
            g_paint_wake.wait(l, [] {
                if (g_drop_question) return true;
                for (const Order& o : g_orders) {
                    if (o.wanted) return true;
                }
                return false;
            });
            for (int i = 0; i < kPieces; ++i) {
                mine[i] = std::move(g_orders[i]);
                g_orders[i] = Order{};
            }
            drop = g_drop_question;
            g_drop_question = false;
        }
        if (drop) {
            // The question closed: its pictures let go of (the dim and the whole picture are the area's size each, 33 MB
            // at 4K), the card's frame with them.
            question = QuestionPaint{};
        }
        Painted out[kPieces];
        for (int i = 0; i < kPieces; ++i) {
            const Order& o = mine[i];
            if (!o.wanted || !o.shots) continue;
            const std::int64_t began = now_ns();
            switch (i) {
            case kQuestionPiece: out[i] = paint_question(o, question); break;
            case kBarPiece: out[i] = paint_bar(o, paints[i]); break;
            case kNoticePiece: out[i] = paint_notice(o, paints[i]); break;
            case kCounterPiece: out[i] = paint_counter(o, paints[i]); break;
            case kHandlePiece: out[i] = paint_handle(o, paints[i]); break;
            default: break;
            }
            // Its time, for the stats line.
            const auto spent = static_cast<std::uint64_t>(now_ns() - began);
            g_paint_count.fetch_add(1, std::memory_order_relaxed);
            g_paint_ns.fetch_add(spent, std::memory_order_relaxed);
            std::uint64_t most = g_paint_most_ns.load(std::memory_order_relaxed);
            while (spent > most && !g_paint_most_ns.compare_exchange_weak(most, spent, std::memory_order_relaxed)) {
            }
        }
        bool any = false;
        {
            std::lock_guard<std::mutex> l(g_paint_lock);
            for (int i = 0; i < kPieces; ++i) {
                if (!out[i].ready) continue;
                g_painted[i] = std::move(out[i]);
                any = true;
            }
        }
        // The UI thread takes them when it gets to the message.
        if (any && g_clock) PostMessageW(g_clock, kPaintedMessage, 0, 0);
    }
}

// What the last read was, as the UI thread took it (none yet: an empty list), how many reads there have been by then
// (glass::take()), and when it came.
std::shared_ptr<const std::vector<glass::Shot>> g_shots = std::make_shared<const std::vector<glass::Shot>>();
unsigned g_shots_seen = 0;
UINT64 g_shots_at = 0;

// The view as the windows have it now, with the room the bar takes.
View view_now() {
    View v;
    v.w = area_w();
    v.h = area_h();
    v.dpi = window_dpi();
    v.top_room = top_room();
    v.full = g_hooks.fullscreen && g_hooks.fullscreen();
    return v;
}

// An order for a piece handed to the painter, the frame's last read with it; the painter wakes for it.
void order(Piece piece, Order o) {
    o.wanted = true;
    if (!o.shots) o.shots = g_shots;
    {
        std::lock_guard<std::mutex> l(g_paint_lock);
        g_orders[piece] = std::move(o);
    }
    g_paint_wake.notify_one();
}

// ---- the pieces on the screen (the UI thread's)

// A piece's window and what it shows: the picture handed back last for it, its place in the game's area, its opacity,
// whether it is on the screen, whether its picture has the frame behind it, and since when it waits for one that has.
struct Shown {
    HWND window = nullptr;
    std::shared_ptr<Canvas> picture;
    int x = 0, y = 0;
    BYTE alpha = 255;
    bool up = false;
    bool glass = false;
    unsigned made = 0;
    std::string key;
    UINT64 wanted = 0;
    // Moved (the bar came or went, the area's size changed) while on the screen: since when its new picture waits for
    // the frame behind its new place, and that place grown by the blur's reach, which the read takes in (0: none).
    UINT64 moving = 0;
    glass::Rect next{0, 0, 0, 0};
    // What its picture carries for a motion (Painted's): the rows at its top the motion counts by, and the room the
    // bar took in the view its place was worked out for.
    int rows = 0, room = 0;
    // Where a motion has it now: `down` rows lower than its picture's place, and without the top `cut` rows of its
    // picture (the bar sliding out of the game's top edge, the handle's rail under the bar's foot).
    int down = 0, cut = 0;
    // What the screen shows of it now: the picture's number, its place on the screen, its opacity and its cut.
    unsigned shown_made = 0;
    POINT at{-1, -1};
    BYTE shown_alpha = 0;
    int shown_cut = 0;
};

// The time the UI thread spends handing pictures to UpdateLayeredWindow, for the stats line.
std::uint64_t g_show_count = 0, g_show_ns = 0, g_show_most_ns = 0;

// The piece on the screen as it is now: its picture handed to UpdateLayeredWindow when anything of it changed (the
// picture, its place, its opacity, how much of its top is cut), and its window shown, without taking the focus, the
// first time. A motion's step is this one call: the picture is not made again, only placed, cut and faded.
void show(Shown& s) {
    if (!s.picture || !s.picture->bits || !showing()) return;
    const RECT a = area();
    // Never without its last row (a window has at least one): a piece cut away whole is hidden by its owner instead.
    const int cut = std::clamp(s.cut, 0, s.picture->h - 1);
    const POINT at{a.left + s.x, a.top + s.y + s.down};
    if (s.up && s.shown_made == s.made && at.x == s.at.x && at.y == s.at.y && s.alpha == s.shown_alpha && cut == s.shown_cut) return;
    const std::int64_t began = now_ns();
    s.picture->show(s.window, at.x, at.y, s.alpha, cut);
    const auto spent = static_cast<std::uint64_t>(now_ns() - began);
    ++g_show_count;
    g_show_ns += spent;
    g_show_most_ns = std::max(g_show_most_ns, spent);
    s.shown_made = s.made;
    s.at = at;
    s.shown_alpha = s.alpha;
    s.shown_cut = cut;
    if (!s.up) {
        ShowWindow(s.window, SW_SHOWNOACTIVATE);
        s.up = true;
    }
}

// The piece off the screen, at its own place the next time it comes.
void hide(Shown& s) {
    if (s.up && showing()) ShowWindow(s.window, SW_HIDE);
    s.up = false;
    s.wanted = 0;
    s.moving = 0;
    s.down = 0;
    s.cut = 0;
}

// Whether a message is Windows showing a piece's window again by itself, for a piece the overlay does not have up: such
// a showing is refused (its window procedure answers it without passing it on). Windows hides an owner's pop-ups itself
// when the owner is minimised, and when it comes back it shows again those it hid (WM_SHOWWINDOW with SW_PARENTOPENING,
// which DefWindowProc acts on). A piece put away meanwhile (the bar, the counter and the handle as the game is minimised,
// a notice whose time ran out) was already hidden then, so its own SW_HIDE changed nothing and Windows still meant to show
// it: its last picture came back over the game while the overlay held it gone, and the bar's chips let clicks through to
// the game's own X under them. Wine hides nothing at a minimise, so only Windows itself showed it. A piece that is up
// comes back as Windows brings it; one that is not stays hidden until the overlay shows it.
bool system_reshow(const Shown& s, UINT msg, WPARAM w, LPARAM l) { return msg == WM_SHOWWINDOW && w && l == SW_PARENTOPENING && !s.up; }

// Whether the piece's picture may go on the screen: one is there, with the frame behind it, or the render thread cannot
// read the frame here, or the piece has waited for one long enough.
bool ready(const Shown& s) {
    if (!s.picture) return false;
    if (s.glass || glass::refused()) return true;
    return s.wanted && GetTickCount64() - s.wanted >= kGlassWaitMs;
}

// Whether a new picture for a piece goes to it: always, unless the piece is on the screen with the frame behind it and
// the new one has none yet (it moved, and the read for its new place has not come): the one shown then stays, up to the
// glass's wait, so that a piece never flashes its bare tint as it moves.
bool accept(Shown& s, const Painted& p) {
    if (!s.up || p.glass || !s.glass || glass::refused() || !p.picture) {
        s.moving = 0;
        return true;
    }
    const UINT64 now = GetTickCount64();
    if (!s.moving) s.moving = now;
    if (now - s.moving >= kGlassWaitMs) {
        s.moving = 0;
        return true;
    }
    s.next = glass::Rect{p.x - blur_reach(), p.y - blur_reach(), p.picture->w + 2 * blur_reach(), p.picture->h + 2 * blur_reach()};
    return false;
}

// A picture handed back, taken for its piece.
void take(Shown& s, Painted& p) {
    s.picture = std::move(p.picture);
    s.x = p.x;
    s.y = p.y;
    s.glass = p.glass;
    s.made = p.made;
    s.key = std::move(p.key);
    s.rows = p.rows;
    s.room = p.room;
}

void glass_wish();

// ---- the bar (the UI thread's)

Shown g_bar;
// The handle's window too (its own part comes after the bar's): the bar is kept just under it.
Shown g_handle;
int g_bar_hover = kNone;
// When the bar last had the pointer on it (or came), and how long it stays down after that before it goes up.
UINT64 g_bar_since = 0, g_bar_stay = 0;
// The bar's one timer: a look for its picture before it comes, a look now and then while it is on its way, a look at
// the pointer while it is down.
constexpr UINT_PTR kBarTimer = 2;
// Down for 600 ms after the pointer leaves it, then up; shown by a finger, down for 4 s (a finger has no pointer that
// stays on it); by itself (the game's first picture, a switch), down for 3 s. While down it looks for the pointer ten
// times a second. Its way down and its way up take overlay_motion.h's times.
constexpr UINT64 kBarStayMs = 600, kBarTouchStayMs = 4000, kBarRevealMs = 3000, kBarLookMs = 100;
// Shown by a finger: the pointer Windows parks where the finger was is no mouse on the bar, until the mouse moves.
bool g_bar_by_touch = false;
// The chip the mouse's button (or a finger) went down on: it acts only when let go on the same chip, and looks pressed
// while it is held there.
int g_bar_pressed = kNone;
// Where the bar stood when the button went down: the rows of its picture its way had cut then. The pointer is read
// against that place until the button comes up, so that a chip pressed while the bar slides (its way moves it some 30
// rows in a tenth of a second early on) acts when let go where it was pressed, as at rest.
int g_bar_press_cut = 0;
// The pointer at the top edge or on the handle waits this long before the bar comes, and brings it only if it is still
// there: a pointer on its way to the window's title bar above, or flicked past the edge mid-song, brings nothing.
constexpr UINT_PTR kBarEdgeTimer = 4;
constexpr UINT kBarEdgeMs = 150;
// Whether the mouse's button was down at its last move over the game (it plays then: no bar).
bool g_pointer_down = false;
// The game's own input as the window reports it: whether a mouse button or a finger is down on the game now, and when
// the last press or release there was. The bar comes from the top edge or the handle only once the game has had none
// for this long: a player whose clicks or held notes are at the top of a song never brings it.
bool g_game_down = false;
UINT64 g_game_pressed = 0;
constexpr UINT64 kQuietMs = 1500;
// The pointer came to rest at the top edge or on the handle by moving there (not by a press where it already was):
// the edge's wait may bring the bar. Any press, and a move away, takes it back.
bool g_rest_armed = false;
// Where the last move put the pointer (in the game's window): a move message to the same place is no move.
int g_moved_x = -1, g_moved_y = -1;
// Until when a bar that came by itself stays down whatever the pointer does (0: none).
UINT64 g_bar_reveal_until = 0;
// The bar is wanted on the screen (from when it is asked for until it has gone up), or may come (the pointer waits at
// the edge): the frame behind it is read meanwhile, so that it comes as glass rather than its bare tint.
bool g_bar_wanted = false, g_bar_coming = false;
// Why it comes, for the log line when it does.
const char* g_bar_why = "";
// What was ordered of the painter last for it: its look and the read it was ordered with.
std::string g_bar_ordered;
const void* g_bar_ordered_shots = nullptr;
// The bar's way between up and down (overlay_motion.h), and where its last step had it.
Slide g_slide;
float g_bar_place = 0;
// Whether a way is under way: from when it began until a step has seen its end and settled the bar (down, or gone).
// The steps go on until then, whatever the clock says between two looks at it: a way is never left a step short.
bool g_bar_on_way = false;
// While on a way the bar's own timer looks this often as well: should the display's steps fail to come, the way still
// ends in its time.
constexpr UINT64 kBarWayLookMs = 50;

// Whether the frame is in full screen, as the window says.
bool full_screen() { return g_hooks.fullscreen && g_hooks.fullscreen(); }

// The rows of the bar in sight now, as its last step showed them (none while it is off the screen).
int bar_in_sight() { return g_bar.up ? std::max(0, g_bar.rows - g_bar.cut) : 0; }

// How much lower than its picture's place a piece at the game's top is shown now: the rows of the bar in sight, less
// the room the bar took where its place was worked out. Nothing once the bar has settled and the piece is placed for it.
int under_bar(const Shown& s) { return piece_down(bar_in_sight(), s.room); }

// The bar's look as text: its size, the scale, the chip under the pointer, the one held, full screen or not.
std::string bar_key(const View& v) {
    char key[96];
    std::snprintf(key, sizeof key, "bar %dx%d %.4f %d %d %d", v.w, v.h, static_cast<double>(v.dpi), g_bar_hover, g_bar_pressed, v.full ? 1 : 0);
    return key;
}

// The bar's picture as it should look now, asked of the painter unless asked already with the same read.
void order_bar() {
    View v = view_now();
    // The bar itself never moves under itself.
    v.top_room = 0;
    const std::string key = bar_key(v);
    if (key == g_bar_ordered && g_shots.get() == g_bar_ordered_shots) return;
    // On its way with a picture of this look: that one picture is only moved, cut and shown until the bar is there (no
    // picture is made during a motion); the frame's newer reads are taken up again once it has settled.
    if (g_slide.moving(now_ns()) && g_bar.picture && g_bar.key == key) return;
    g_bar_ordered = key;
    g_bar_ordered_shots = g_shots.get();
    Order o;
    o.view = v;
    o.hover = g_bar_hover;
    o.pressed = g_bar_pressed;
    o.key = key;
    order(kBarPiece, std::move(o));
}

void handle_update();
void counter_place();
void notice_frame();
void motion_start();
void trace_step(const Slide& way, std::int64_t now, float place, int rows);
void trace_settled(std::int64_t now);
void trace_cut(std::int64_t now);
// Whether the bar is being hidden by its own way's last step (bar_step), not put away at once midway.
bool g_bar_way_over = false;

// The notice and a counter in a top corner, placed again for the bar's coming or going (under it, or back up).
void move_for_bar() {
    counter_place();
    notice_frame();
}

// The bar gone: hidden at once wherever its way had it, its timer stopped, nothing under the pointer or held on it.
void hide_bar() {
    if (!g_bar.window) return;
    const bool was = g_bar.up, room = g_bar_room;
    hide(g_bar);
    // Put away at once in the middle of a way (the window minimised): the trace says so.
    if (!g_bar_way_over) trace_cut(now_ns());
    // Up, at rest: the next time it comes, from the top edge again.
    g_slide.rest(0);
    g_bar_place = 0;
    g_bar_on_way = false;
    g_bar_room = false;
    g_bar_wanted = false;
    g_bar_reveal_until = 0;
    KillTimer(g_bar.window, kBarTimer);
    g_bar_hover = kNone;
    // A chip held as it goes is let go of without acting: forgotten before the capture goes, so that the bar's
    // WM_CAPTURECHANGED finds nothing held and does not draw the bar again.
    const bool held = g_bar_pressed != kNone;
    g_bar_pressed = kNone;
    if (held && GetCapture() == g_bar.window) ReleaseCapture();
    // Its picture let go of: the next time it comes, a picture of then, never one of before.
    g_bar.picture.reset();
    g_bar.key.clear();
    g_bar_ordered.clear();
    if (was) note("player: the bar goes up");
    // The pieces that were placed under it, or moved with it, at their own place again.
    if (was || room) move_for_bar();
    glass_wish();
    handle_update();
}

// Whether the mouse's pointer is on the part of the bar in sight at the top of the game's area (shown by a finger, it
// is not until the mouse moves).
bool pointer_on_bar() {
    if (g_bar_by_touch || !g_bar.up) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    return p.x >= a.left && p.x < a.right && p.y >= a.top && p.y < a.top + bar_in_sight();
}

// The handle's window just above the bar's, whatever showing and hiding did to their order since they were made: on the
// bar's way the handle hangs from the bar's foot, over the bar's shadow. Only its place among the windows right above
// the bar changes: it goes under the window that is above the bar now (at the top where the bar is the top one), never
// over another program's window that the bar is under.
void handle_above_bar() {
    if (!showing() || !g_handle.window || !g_bar.window) return;
    // The window above the bar, the handle itself aside.
    HWND above = GetWindow(g_bar.window, GW_HWNDPREV);
    if (above == g_handle.window) above = GetWindow(g_handle.window, GW_HWNDPREV);
    SetWindowPos(g_handle.window, above ? above : HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
}

// How many windows above the bar's are looked at for the game's own (bar_above_game): it is put right above the bar,
// with at most the handle between.
constexpr int kOrderLook = 4;

// The bar's window above the game's, where the game's has got above it. Windows keeps a window above the one that owns
// it, and there this finds nothing to do. Wine (the checks run on it) puts a window that its screen uncovers a part of
// right above the window that covered it: the game's window above the bar, each time a step of the bar's way or the
// handle's going leaves a pixel of the game free. The bar is still seen there, but the mouse is the game's on it: its
// chips would neither light nor take a click. So each step and each look of the bar puts it back just above the
// game's window (under the window that is above that one: never over another program's), and the handle above it.
void bar_above_game() {
    // Only a bar on the screen has a place among the windows to keep.
    if (!showing() || !g_bar.window || !g_bar.up || !g_frame) return;
    // The windows above the bar's, one by one from the bar up.
    HWND above = g_bar.window;
    for (int looked = 0; looked < kOrderLook; ++looked) {
        // The next window up; none: the bar is the top one, the game's is under it.
        above = GetWindow(above, GW_HWNDPREV);
        if (!above) return;
        // Another window (the handle, the question, another program's): the one above it next.
        if (above != g_frame) continue;
        // The game's window is above the bar: the bar goes right above it, under the window that is above the game's
        // now (at the top where the game's is the top one).
        HWND over = GetWindow(g_frame, GW_HWNDPREV);
        SetWindowPos(g_bar.window, over ? over : HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
        // The handle over the bar's shadow again, wherever that left it.
        handle_above_bar();
        return;
    }
}

// The counter's window where its place and the bar have it now: in a top corner it is lower by the rows of the bar in
// sight (it moves with the bar's foot); at the bottom the bar never moves it.
void counter_show();
// The notice's window where its own slide and the bar have it now.
void notice_show();

// One step of the bar's way: the part of it that its place now leaves in sight is shown at the game's top edge (the
// foot of its picture first: it slides out of the edge and never over the window's title bar above), and the handle,
// the notice and a counter in a top corner are moved with its foot. Down, whole: the pieces at the top are placed for
// it and made again over the frame behind their new place. Up, out of sight: it is hidden. The pictures are the ones
// made before the way began: a step only places them.
void bar_step() {
    // Only a bar wanted or on the screen is on a way.
    if (!g_bar.window || !g_bar.picture || !(g_bar_wanted || g_bar.up)) return;
    const std::int64_t now = now_ns();
    // The way as it is at this step (a bar that goes is put to rest below, before its last step is told).
    const Slide way = g_slide;
    const float place = way.at(now);
    const int rows = bar_rows(place, g_bar.rows);
    if (rows <= 0) {
        // Out of sight. Headed up: gone, the handle and the pieces at the top at their own place again. Headed down: its
        // first step, nothing of it to show yet.
        const bool gone = way.to <= 0.0f && g_bar.up;
        if (gone) {
            g_bar_way_over = true;
            hide_bar();
            g_bar_way_over = false;
        }
        trace_step(way, now, place, rows);
        if (gone) trace_settled(now);
        return;
    }
    const bool coming = !g_bar.up;
    g_bar_place = place;
    // Its foot at the edge first: the picture without the rows still above the edge, whole in opacity all the way.
    g_bar.cut = g_bar.rows - rows;
    g_bar.alpha = 255;
    show(g_bar);
    // Above the game's window still: its chips take the pointer.
    bar_above_game();
    if (coming && g_bar.up) {
        g_bar_coming = false;
        char line[160];
        std::snprintf(line, sizeof line, "player: the bar comes down (%s)", g_bar_why);
        note(line);
        handle_above_bar();
        glass_wish();
    }
    // The handle on its foot, fading; the pieces at the top lower by what is in sight.
    handle_update();
    counter_show();
    notice_show();
    trace_step(way, now, place, rows);
    if (way.moving(now)) return;
    // The way's end seen: settled.
    g_bar_on_way = false;
    trace_settled(now);
    if (g_slide.to >= 1.0f && !g_bar_room) {
        // Down, whole: from now on the notice and a counter at the top are placed under it (their pictures made again
        // over the frame behind their new place, which they already stand at), and its own picture follows the frame's
        // reads again.
        g_bar_room = true;
        move_for_bar();
        order_bar();
        glass_wish();
    }
}

// Whether Windows shows animations (its "Animation effects" setting): where it does not, nothing of the overlay moves
// by steps, and the pieces come and go at once. Asked of Windows at most twice a second.
bool animations() {
    static UINT64 asked = 0;
    static bool on = true;
    const UINT64 now = GetTickCount64();
    if (!asked || now - asked >= 500) {
        asked = now;
        BOOL shown = TRUE;
        // Where Windows cannot say, as if they were on.
        on = !SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &shown, 0) || shown;
    }
    return on;
}

// The bar where its time has it: down while the pointer is on it and for g_bar_stay after (or a reveal's own time),
// then up; up at once while the question is up. It sets out on its way down once its picture for its look now has come
// (with the frame behind it, or after the wait), and on its way up when its time is over; a way under way turns back
// from where it is. Its one timer is set for its next look.
void bar_frame() {
    if (!g_bar.window) return;
    const UINT64 now = GetTickCount64();
    if (pointer_on_bar()) {
        // On it: its time starts again, and it stays down for kBarStayMs after the pointer leaves.
        g_bar_since = now;
        g_bar_stay = kBarStayMs;
    } else {
        // Off it, perhaps between two of its moves: no chip is under the pointer.
        g_bar_hover = kNone;
    }
    // Down until the later of its stay after the pointer and a reveal's own time (the pointer leaving it does not
    // shorten a reveal); the question takes it up.
    const UINT64 down_until = std::max(g_bar_since + g_bar_stay, g_bar_reveal_until);
    const bool down = now <= down_until && !asking();
    if (!g_bar.up) {
        // Not on the screen, and no longer wanted there (its time ran out before its picture came, or the question
        // opened): nothing comes.
        if (!down) {
            hide_bar();
            return;
        }
        if (!g_bar_wanted) {
            // Wanted from now on: the frame behind it read, and its glass waited for.
            g_bar_wanted = true;
            g_bar.wanted = now;
            glass_wish();
        }
        order_bar();
        View v = view_now();
        v.top_room = 0;
        if (g_bar.key != bar_key(v) || !ready(g_bar)) {
            // Its picture for its look now is not there yet (or waits for the frame behind it): a look again soon.
            SetTimer(g_bar.window, kBarTimer, 15, nullptr);
            return;
        }
    } else if (down) {
        // On the screen and staying: its look now (a chip lit or held) asked for, if it changed.
        order_bar();
    }
    // Headed where it belongs from where it is (a way already headed there goes on), and its first step at once.
    g_slide.aim(down ? 1.0f : 0.0f, now_ns(), animations());
    // On a way from now until a step settles it.
    if (g_slide.moving(now_ns())) g_bar_on_way = true;
    bar_step();
    // Gone (a way up that took no time, or its last step).
    if (!g_bar.up && !g_bar_wanted) return;
    // The steps that follow come with the display's refreshes.
    if (g_bar_on_way) motion_start();
    // The next look: on a way, soon (the way's end, should no step come); down, at the pointer, or its time's end if
    // that comes first.
    const UINT64 next = g_bar_on_way ? kBarWayLookMs : std::min(kBarLookMs, down_until - std::min(down_until, now) + 1);
    SetTimer(g_bar.window, kBarTimer, static_cast<UINT>(std::max<UINT64>(1, next)), nullptr);
}

// Whether the mouse's pointer rests at the very top edge of the game's area now (within 4 pixels at 720 lines, over the
// game's own window, its button up), or on the handle while it is there: the wait is over and the bar comes.
bool pointer_at_edge();

// The bar brought down, staying `stay` ms (more while the pointer is on it); `why` for the log when it comes down.
void reveal(UINT64 stay, const char* why) {
    if (!g_bar.window || asking()) return;
    if (!g_bar.up && why) g_bar_why = why;
    g_bar_since = GetTickCount64();
    g_bar_stay = stay;
    bar_frame();
}

// The bar down by itself for `stay` ms whatever the pointer does meanwhile (the game's first picture, a switch between
// a window and full screen), then as usual.
void reveal_for(UINT64 stay, const char* why) {
    if (!g_bar.window || asking()) return;
    g_bar_reveal_until = std::max(g_bar_reveal_until, GetTickCount64() + stay);
    reveal(stay, why);
}

// The bar's rest at the top edge or on the handle let go of: no bar from it (a press, the pointer gone elsewhere).
void rest_cancel() {
    g_rest_armed = false;
    if (g_bar.window) KillTimer(g_bar.window, kBarEdgeTimer);
    if (g_bar_coming) {
        g_bar_coming = false;
        if (!g_bar.up && !g_bar_wanted) {
            // The picture made meanwhile goes too (a later bar is made over the frame then).
            g_bar.picture.reset();
            g_bar.key.clear();
            g_bar_ordered.clear();
        }
        glass_wish();
    }
}

// The chip under a point of the bar's window with the bar where `cut` says: its picture's rows start that many above the
// window's (g_bar.cut: as it is shown now; g_bar_press_cut: as it stood when the button went down).
int bar_chip_at(LPARAM l, int cut) { return chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)) + cut); }

LRESULT CALLBACK bar_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // Gone up while the window was minimised: Windows does not bring its last picture back over the game.
    if (system_reshow(g_bar, msg, w, l)) return 0;
    switch (msg) {
    case WM_TIMER:
        if (w == kBarTimer) bar_frame();
        if (w == kBarEdgeTimer) {
            KillTimer(h, kBarEdgeTimer);
            // Only a rest the pointer came to by moving, still where it rests, no button or finger down on the game.
            if (!g_rest_armed || !pointer_at_edge()) {
                rest_cancel();
                return 0;
            }
            // A press or a release on the game less than kQuietMs ago: the rest waits for the quiet's end (a click and a
            // held note at the top of a song are play, not a wish for the bar).
            const UINT64 since = GetTickCount64() - g_game_pressed;
            if (since < kQuietMs) {
                SetTimer(h, kBarEdgeTimer, static_cast<UINT>(kQuietMs - since), nullptr);
                return 0;
            }
            g_rest_armed = false;
            g_bar_coming = false;
            reveal(kBarStayMs, nullptr);
        }
        return 0;
    case WM_NCHITTEST: {
        // The shadow under the bar is no part of it: the game under it keeps its clicks. On the bar's way, the shadow
        // starts under the rows in sight.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        ScreenToClient(h, &p);
        if (p.y >= bar_in_sight()) return HTTRANSPARENT;
        break;
    }
    case WM_MOUSEMOVE: {
        // A mouse's own move: the pointer is the mouse's again (a finger's moves are Windows' copies, marked).
        if (!from_touch()) g_bar_by_touch = false;
        // The chip under the pointer lights up (where the bar's way has it now); while the button is held, where the bar
        // stood when it went down, so that the chip held stays sunk under a still pointer as the bar slides on.
        const int now = bar_chip_at(l, g_bar_pressed != kNone ? g_bar_press_cut : g_bar.cut);
        if (now != g_bar_hover) {
            g_bar_hover = now;
            bar_frame();
            // On the X, the whole frame is read ahead: the question that may follow has its backdrop at once.
            glass_wish();
        }
        return 0;
    }
    case WM_LBUTTONDOWN:
        // On its way up for the question: its chips no longer take a press.
        if (asking()) return 0;
        // Held on a chip: it looks pressed, and the bar keeps the mouse until it is let go. The bar's place now kept: the
        // release is read against it, wherever the bar's way takes it meanwhile.
        g_bar_press_cut = g_bar.cut;
        g_bar_pressed = bar_chip_at(l, g_bar_press_cut);
        g_bar_hover = g_bar_pressed;
        SetCapture(h);
        bar_frame();
        glass_wish();
        return 0;
    case WM_CAPTURECHANGED:
        // The mouse taken away while held (another window, a system dialog): nothing acts.
        if (g_bar_pressed != kNone) {
            g_bar_pressed = kNone;
            bar_frame();
        }
        return 0;
    case WM_LBUTTONUP: {
        // Only a chip let go of where it was pressed acts: a press slid off it, or onto it from elsewhere, does nothing.
        // Read against the bar's place at the press: a chip pressed as the bar slides, the pointer still, is let go on
        // it, though the way has moved it from under the pointer since.
        const int pressed = g_bar_pressed;
        const int chip_now = bar_chip_at(l, g_bar_press_cut);
        g_bar_pressed = kNone;
        // From now on the pointer is read where the bar is: the chip under it now lights.
        g_bar_hover = bar_chip_at(l, g_bar.cut);
        if (GetCapture() == h) ReleaseCapture();
        bar_frame();
        // A finger's tap: the bar stays for the finger's time after it, not while Windows' parked pointer sits there.
        if (from_touch()) {
            g_bar_by_touch = true;
            g_bar_since = GetTickCount64();
            g_bar_stay = kBarTouchStayMs;
        }
        // The keyboard back to the game's window: the bar never takes it, another program may have.
        SetForegroundWindow(g_frame);
        // The X asks before quitting; the full screen chip switches at once (the window redraws the bar for it);
        // minimise minimises the game's window, as its own button did (the window holds the game and hides all this).
        if (chip_now != pressed) return 0;
        if (chip_now == kQuitChip) ask_quit();
        else if (chip_now == kScreenChip && g_hooks.toggle_fullscreen) g_hooks.toggle_fullscreen();
        else if (chip_now == kMinChip) ShowWindow(g_frame, SW_MINIMIZE);
        return 0;
    }
    case WM_SETCURSOR:
        // The game's pointer over the bar too.
        SetCursor(cursor(false));
        return TRUE;
    case WM_MOUSEACTIVATE:
        // A click on the bar leaves the game's window active.
        return MA_NOACTIVATE;
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

// ---- the question before quitting (the UI thread's)

Shown g_ask;
// Whether it is up (or asked and waiting for its backdrop or its picture), the button the keys chose (Keep playing
// first) and what is under the pointer.
bool g_asking = false;
int g_choice = kKeep;
int g_ask_hover = kNone;
// What the mouse's button (or a finger) went down on: a button, the thin X, beside the card (kBeside), or kNone (the
// card's own body); only a release on the same acts, and a button held looks pressed in.
int g_ask_pressed = kNone;
// Whether the window is minimised with the game held for it, and whether the game is held now (for either).
bool g_minimised_hold = false, g_held = false;
// Asked, and waiting (at most kAskWaitMs) for the render thread's read of the whole frame, which the dim blurs: the
// question is ordered of the painter once it is there, or bare after the wait. The read's count when it was asked for.
bool g_ask_waiting = false;
// Whether the read it shows over was made ahead (the X under the pointer).
bool g_ask_ahead = false;
unsigned g_ask_after = 0;
UINT64 g_ask_asked = 0;
constexpr UINT64 kAskWaitMs = 150;
// Asked over a minimised window (the taskbar's Close on it): the game drew nothing while it was held there, so the window
// comes back and the game goes on until it has drawn its picture again, and only then holds for the question, which shows
// over the game's own picture rather than over a black window. The count of frames shown when it was asked (the log says
// how many the game showed before the question came).
bool g_ask_restoring = false;
unsigned long long g_ask_frames = 0;
// How long that waits for the game's picture at most: the game's resume takes a few frames (a slow computer's more), and
// a game that shows nothing but black meanwhile gets its question all the same.
constexpr UINT64 kAskRestoreWaitMs = 1500;
// A read of the whole frame younger than this is taken as it is: the X under the pointer had it read ahead.
constexpr UINT64 kAskFreshMs = 250;

void fps_look_now();

// The game held still while the question is up (from when its picture is being made: a read of the frame it dims is
// in hand) or the window is minimised, and let go on when neither is: the window is told only of a change. The counter
// and the handle hide while it is held.
void update_hold() {
    const bool want = (g_asking && !g_ask_waiting) || g_minimised_hold;
    if (want == g_held) return;
    g_held = want;
    if (g_hooks.hold) g_hooks.hold(want);
    fps_look_now();
    handle_update();
}

Shown g_notice;
bool g_notice_up = false;

// The question's picture as it should look now (its choice, the pointer, the press), asked of the painter, over the
// frame's last read and the notice as the screen shows it.
void order_question() {
    Order o;
    o.view = view_now();
    o.choice = g_choice;
    o.hover = g_ask_hover;
    o.pressed = g_ask_pressed;
    if (g_notice_up && g_notice.up && g_notice.picture) {
        o.under = g_notice.picture;
        o.under_x = g_notice.x;
        // Where the screen has it now: lower than its picture's place while the bar's rows in sight say so.
        o.under_y = g_notice.y + g_notice.down;
    }
    char key[96];
    std::snprintf(key, sizeof key, "question %dx%d %.4f %d %d %d", o.view.w, o.view.h, static_cast<double>(o.view.dpi), g_choice, g_ask_hover, g_ask_pressed);
    o.key = key;
    order(kQuestionPiece, std::move(o));
}

// The question asked of the painter now that its frame was read (or waited for long enough); it shows when it comes.
void paint_ask() {
    g_ask_waiting = false;
    order_question();
    // The game held from now on (a minimised game that comes back for the question stays held).
    update_hold();
}

// The question's picture on the screen: the first time over the dimmed game and above everything else of the overlay,
// the game held then; after that, each new look.
void show_ask() {
    if (!g_asking || !g_ask.picture) return;
    const bool first = !g_ask.up;
    g_ask.x = 0;
    g_ask.y = 0;
    g_ask.alpha = 255;
    show(g_ask);
    if (!first || !g_ask.up) return;
    // Said once a question: whether the frame behind it was read (ahead, while the X was under the pointer, or once
    // asked), and how long after it was asked it showed, its picture's making included.
    const char* over = !g_ask.glass       ? "the bare dim (no read of the frame came)"
                       : g_ask_restoring ? "the game's picture drawn again after the window came back"
                       : g_ask_ahead     ? "the frame read ahead"
                                         : "the frame read for it";
    // Over a window that came back from minimised: how many frames the game showed meanwhile (its picture again, held
    // once the question was made).
    char frames[80] = "";
    if (g_ask_restoring && g_hooks.frames) {
        std::snprintf(frames, sizeof frames, ", %llu frames shown since it was asked", g_hooks.frames().count - g_ask_frames);
    }
    char line[260];
    std::snprintf(line, sizeof line, "player: glass: the question over %s, shown %llu ms after it was asked%s", over,
                  static_cast<unsigned long long>(GetTickCount64() - g_ask_asked), frames);
    note(line);
    if (showing()) {
        // Above everything else of the overlay: the notice stays under its dim.
        SetWindowPos(g_ask.window, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    }
    update_hold();
}

// A new look of the question (the keys' choice, the pointer, a press), once it is on the screen or being made.
void draw_ask() {
    if (!g_asking || g_ask_waiting) return;
    order_question();
}

// The question gone; the game goes on (unless minimised), or ends when `quit`. Its pictures go with it: the painter's
// and the window's (the area's size each).
void answer(bool quit) {
    if (!g_asking) return;
    g_asking = false;
    g_ask_waiting = false;
    g_ask_restoring = false;
    hide(g_ask);
    g_ask.picture.reset();
    g_ask.key.clear();
    {
        std::lock_guard<std::mutex> l(g_paint_lock);
        // An order not taken yet is no longer wanted, and the painter lets its pictures go.
        g_orders[kQuestionPiece] = Order{};
        g_painted[kQuestionPiece] = Painted{};
        g_drop_question = true;
    }
    g_paint_wake.notify_one();
    update_hold();
    glass_wish();
    handle_update();
    if (quit && g_hooks.quit) g_hooks.quit();
}

LRESULT CALLBACK ask_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // As every piece: only a card still asked comes back with the window.
    if (system_reshow(g_ask, msg, w, l)) return 0;
    const int x = static_cast<short>(LOWORD(l)), y = static_cast<short>(HIWORD(l));
    switch (msg) {
    case WM_MOUSEMOVE: {
        // The window hears when the pointer leaves it (off the game), to light nothing then.
        TRACKMOUSEEVENT t{sizeof t, TME_LEAVE, h, 0};
        TrackMouseEvent(&t);
        // What is under the pointer is lit; the keys' choice stays where the keys put it.
        const int hover = ask_at(x, y);
        if (hover != g_ask_hover) {
            g_ask_hover = hover;
            draw_ask();
        }
        return 0;
    }
    case WM_MOUSELEAVE:
        if (g_ask_hover != kNone) {
            g_ask_hover = kNone;
            draw_ask();
        }
        return 0;
    case WM_LBUTTONDOWN:
        // Held: on a button, the thin X, beside the card or on its body; the question keeps the mouse until let go.
        g_ask_pressed = in_card(x, y) ? ask_at(x, y) : kBeside;
        g_ask_hover = ask_at(x, y);
        SetCapture(h);
        draw_ask();
        return 0;
    case WM_CAPTURECHANGED:
        // The mouse taken away while held: nothing acts.
        if (g_ask_pressed != kNone) {
            g_ask_pressed = kNone;
            if (asking()) draw_ask();
        }
        return 0;
    case WM_LBUTTONUP: {
        const int pressed = g_ask_pressed;
        g_ask_pressed = kNone;
        if (GetCapture() == h) ReleaseCapture();
        // The keyboard back to the game's window: the question never takes it, another program may have.
        SetForegroundWindow(g_frame);
        const int at = in_card(x, y) ? ask_at(x, y) : kBeside;
        // Only a release where the press was acts: a press slid from Keep playing onto Quit the game (or from the game
        // beside the card) does nothing. Quit the game quits; Keep playing, the thin X and a click beside the card keep
        // playing.
        if (at != pressed || at == kNone) {
            draw_ask();
            return 0;
        }
        if (at == kQuit) answer(true);
        else answer(false);
        return 0;
    }
    case WM_SETCURSOR:
        // The game's pointer over the question as well.
        SetCursor(cursor(false));
        return TRUE;
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

// ---- the frame counter (the UI thread's)

Shown g_fps;
// Its corner (Settings::ShowFps's order, 0 none), its looks at the count and what they show.
int g_fps_corner = 0;
FrameRate g_rate;
Reading g_reading;
constexpr UINT_PTR kFpsTimer = 3;
// Twice a second; ten times a second while it waits for a frame or for its first measure after one.
constexpr UINT kFpsMs = 500, kFpsWaitMs = 100;
// Whether it was up at the last look, for the log's line when it comes or goes.
bool g_fps_said_up = false;

// The counter's look as text: its numbers (the time to a tenth of a millisecond, as it shows), its corner, its view.
std::string fps_key(const View& v) {
    char key[96];
    std::snprintf(key, sizeof key, "counter %dx%d %.4f %d %d %d %.1f", v.w, v.h, static_cast<double>(v.dpi), v.top_room, g_fps_corner, g_reading.fps,
                  static_cast<double>(g_reading.ms));
    return key;
}

// The counter where the bar's way has it now (bar_step's part of it).
void counter_show() {
    if (!g_fps.window || !g_fps.picture) return;
    // Only on the screen already: a step never brings it up (counter_place does, once its picture is ready).
    if (!g_fps.up) return;
    g_fps.down = g_fps_corner == 1 || g_fps_corner == 2 ? under_bar(g_fps) : 0;
    show(g_fps);
}

// The counter where its look and place are now: asked of the painter for a new look or a new read, on the screen once
// its picture is ready, off it while its reading hides it.
void counter_place() {
    if (!g_fps.window || !g_fps_corner) return;
    if (!g_reading.shown) {
        if (g_fps.up) hide(g_fps);
        g_fps.wanted = 0;
        return;
    }
    if (!g_fps.wanted && !g_fps.up) {
        // Wanted on the screen from now on: its picture waits for the frame behind it.
        g_fps.wanted = GetTickCount64();
        glass_wish();
    }
    const View v = view_now();
    const std::string key = fps_key(v);
    Order o;
    o.view = v;
    o.corner = g_fps_corner;
    o.fps = g_reading.fps;
    o.ms = g_reading.ms;
    o.key = key;
    order(kCounterPiece, std::move(o));
    g_fps.alpha = kCounterAlpha;
    // Its picture for this look on the screen; while a new look is made, the one it shows stays. In a top corner it
    // stands lower by the rows of the bar in sight that its place did not count with.
    if (g_fps.up || (g_fps.key == key && ready(g_fps))) {
        g_fps.down = g_fps_corner == 1 || g_fps_corner == 2 ? under_bar(g_fps) : 0;
        show(g_fps);
    }
}

// A look at the count now: what it shows, and when to look again (sooner while it waits for frames).
void fps_look_now() {
    if (!g_fps.window || !g_fps_corner || !g_hooks.frames) return;
    // The count, then the moment of the look on the count's own clock (the steady clock frames.cpp stamps frames with).
    const FrameCount count = g_hooks.frames();
    g_reading = g_rate.look(count, now_ns(), g_held || g_minimised_hold);
    // Said when it comes up or goes, with why.
    if (g_reading.shown != g_fps_said_up) {
        g_fps_said_up = g_reading.shown;
        if (g_reading.shown) {
            note("player: the frame counter is up");
        } else {
            note(g_held || g_minimised_hold ? "player: the frame counter hides while the game is held" : "player: the frame counter waits for the game's frames");
        }
    }
    counter_place();
    SetTimer(g_fps.window, kFpsTimer, g_rate.waiting() ? kFpsWaitMs : kFpsMs, nullptr);
    glass_wish();
}

LRESULT CALLBACK fps_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // Hidden while the game was held for the minimise: Windows does not bring back its old numbers.
    if (system_reshow(g_fps, msg, w, l)) return 0;
    if (msg == WM_TIMER && w == kFpsTimer) {
        fps_look_now();
        return 0;
    }
    // Clicks go through it to the game: it only tells.
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(h, msg, w, l);
}

// ---- the notice (the UI thread's)

std::string g_notice_text;
bool g_notice_live = false;
// When it first went on the screen, on the steady clock in nanoseconds (0: not yet; it slides in from then).
std::int64_t g_notice_shown = 0;
constexpr UINT_PTR kNoticeTimer = 1;
// Sliding in (12 pixels down, fading in, easing out), staying, fading out.
constexpr float kSlideMs = 220, kStayMs = 6000, kFadeMs = 300;
constexpr float kSlide = 12;
// Whether it is sliding in or fading out now: the motion's clock steps it then, with the display's refreshes.
bool g_notice_stepping = false;
// How far above its resting place its slide in has it now, in pixels.
int g_notice_drop = 0;

// The notice's look as text: its words, live or not, the counter's corner beside it, its view.
std::string notice_key(const View& v) {
    char head[96];
    std::snprintf(head, sizeof head, "notice %dx%d %.4f %d %d %d ", v.w, v.h, static_cast<double>(v.dpi), v.top_room, g_fps_corner, g_notice_live ? 1 : 0);
    return head + g_notice_text;
}

// The notice's picture as it should look now, asked of the painter.
void order_notice() {
    const View v = view_now();
    Order o;
    o.view = v;
    o.text = g_notice_text;
    o.live = g_notice_live;
    o.corner = g_fps_corner;
    o.key = notice_key(v);
    order(kNoticePiece, std::move(o));
}

void notice_show() {
    // Only once it has gone on the screen: its first step is notice_frame's.
    if (!g_notice_up || !g_notice_shown || !g_notice.picture) return;
    // Its resting place, less its own slide in, and lower by the rows of the bar in sight that its place did not count
    // with: the window moves alone (the blur hides the difference).
    g_notice.down = under_bar(g_notice) - g_notice_drop;
    show(g_notice);
}

void notice_frame() {
    if (!g_notice_up) return;
    const std::int64_t now = now_ns();
    // Its look again for a new place (the bar has come down or gone up) or a new size of the game's area.
    const View v = view_now();
    const std::string key = notice_key(v);
    if (g_notice.key != key) order_notice();
    if (!g_notice_shown) {
        // Not on the screen yet: it slides in once its picture is there (with the frame behind it, or after the wait).
        if (g_notice.key != key || !ready(g_notice)) {
            SetTimer(g_notice.window, kNoticeTimer, 15, nullptr);
            return;
        }
        g_notice_shown = now;
    }
    // Where Windows shows no animations, its slide in and its fade out take no time: it comes and goes at once.
    const bool animate = animations();
    const float slide = animate ? kSlideMs : 0.0f, fade = animate ? kFadeMs : 0.0f;
    const float t = static_cast<float>(now - g_notice_shown) / 1e6f;
    float alpha = 1, drop = 0;
    if (t < slide) {
        // In: down from a little above, fading in, easing out.
        const float ease = ease_down(t / slide);
        alpha = ease;
        drop = (1 - ease) * fpx(kSlide);
    } else if (t > slide + kStayMs) {
        alpha = fade > 0 ? 1 - std::min(1.0f, (t - slide - kStayMs) / fade) : 0.0f;
    }
    // Gone only once the fade out is over: the first frame of the slide in is transparent as well.
    if (alpha <= 0 && t > slide) {
        KillTimer(g_notice.window, kNoticeTimer);
        hide(g_notice);
        g_notice_up = false;
        g_notice_stepping = false;
        g_notice_drop = 0;
        g_notice.picture.reset();
        g_notice.key.clear();
        glass_wish();
        handle_update();
        return;
    }
    g_notice_drop = static_cast<int>(drop);
    g_notice.alpha = static_cast<BYTE>(alpha * 255);
    notice_show();
    // The next step: with the display's refreshes while it slides or fades (its own timer too, now and then, should
    // those fail to come); while it stays, once, when the fade begins.
    const bool staying = t >= slide && t <= slide + kStayMs;
    g_notice_stepping = !staying;
    if (staying) {
        SetTimer(g_notice.window, kNoticeTimer, static_cast<UINT>(std::max(1.0f, slide + kStayMs - t + 1)), nullptr);
    } else {
        SetTimer(g_notice.window, kNoticeTimer, 50, nullptr);
        motion_start();
    }
}

LRESULT CALLBACK notice_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // Faded while the window was minimised: Windows does not bring it back.
    if (system_reshow(g_notice, msg, w, l)) return 0;
    if (msg == WM_TIMER && w == kNoticeTimer) {
        notice_frame();
        return 0;
    }
    // Clicks go through it to the game: it only tells.
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(h, msg, w, l);
}

// ---- the handle (the UI thread's)

// Whether the game's picture has shown yet: the handle and the bar's reveal wait for it.
bool g_first_picture = false;
// Whether the handle is drawn lit (the pointer on its reach), the view its picture was last asked for (a new view
// takes it off the screen until its picture comes, a change of light alone keeps the one shown meanwhile), and the
// look asked of the painter last (asked once, not again at every step).
bool g_handle_lit = false;
std::string g_handle_view, g_handle_ordered;
// While it is lit, the handle's window looks again every 100 ms whether the pointer is still on it: a pointer that leaves
// over the window's title bar tells the game's window nothing.
constexpr UINT_PTR kHandleTimer = 1;
constexpr UINT kHandleCheckMs = 100;

// Whether the handle may be on the screen at all: once the game's picture has shown, while no notice sits at the top,
// no question is up and the game runs. Where the bar is on its way says the rest (handle_update).
bool handle_allowed() { return g_first_picture && !g_asking && !g_held && !g_minimised_hold && !g_notice_up; }

// Whether the pointer is on the handle's reach now, over the game's window (the handle lets it through), with no
// button down and the game not pressed.
bool pointer_on_handle() {
    if (g_pointer_down || g_game_down) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    return on_handle(p.x - a.left, p.y - a.top) && WindowFromPoint(p) == g_game;
}

// The handle on the screen or off it, as it belongs now, and where the bar's way has it. At rest (no bar): whole, at the
// game's top edge, lit while the pointer is on it. As the bar comes down it hangs from the bar's foot and fades, its
// rail cut as the bar's own foot line takes its place, in the look it had when the bar set out; gone before the bar
// settles. As the bar goes up it comes back the same way. Its picture is asked of the painter for a new view or a
// change of light.
void handle_update() {
    if (!g_handle.window) return;
    if (!handle_allowed()) {
        g_handle_lit = false;
        KillTimer(g_handle.window, kHandleTimer);
        hide(g_handle);
        return;
    }
    // At rest: no bar on the screen and none wanted. Only then does the pointer light it or let it go; under a bar that
    // is down, whole, it goes unlit, so that it comes back as it rests (the pointer that lit it is on the bar, or gone).
    const bool resting = !g_bar.up && !g_bar_wanted;
    if (resting) g_handle_lit = pointer_on_handle();
    else if (g_bar.up && g_bar_place >= 1.0f) g_handle_lit = false;
    // Looked at again while lit and at rest, for a pointer that leaves without a word to the game's window.
    if (g_handle_lit && resting) {
        SetTimer(g_handle.window, kHandleTimer, kHandleCheckMs, nullptr);
    } else {
        KillTimer(g_handle.window, kHandleTimer);
    }
    View v = view_now();
    v.top_room = 0;
    v.full = false;
    char view[64], key[80];
    std::snprintf(view, sizeof view, "handle %dx%d %.4f", v.w, v.h, static_cast<double>(v.dpi));
    std::snprintf(key, sizeof key, "%s %s", view, g_handle_lit ? "lit" : "rest");
    if (g_handle.key != key) {
        if (g_handle_ordered != key) {
            g_handle_ordered = key;
            Order o;
            o.view = v;
            o.key = key;
            o.lit = g_handle_lit;
            order(kHandlePiece, std::move(o));
        }
        // Its picture for another view comes in a moment: off the screen until then. Lit or not, the one shown stays.
        if (g_handle_view != view && g_handle.up) hide(g_handle);
        g_handle_view = view;
        if (!g_handle.up) return;
    }
    // Where the bar's last step had it (up, out of sight, while there is none), and what that leaves of the handle.
    const float place = g_bar.up ? g_bar_place : 0.0f;
    const BYTE alpha = static_cast<BYTE>(std::lround(255.0f * handle_opacity(place)));
    if (alpha == 0) {
        // The bar is down, or nearly: the handle is gone until it goes up again.
        hide(g_handle);
        return;
    }
    // Not on the screen: it comes at rest, and as a bar on the screen goes up; never while a bar is wanted or coming
    // down (after the game's first picture the bar comes first, and the handle is first seen as that bar goes up).
    if (!g_handle.up && !resting && !(g_bar.up && g_slide.to <= 0.0f)) return;
    // On the bar's foot: lower by the bar's rows in sight, its rail cut as far as the bar covers it.
    const Hang hang = handle_hang(bar_in_sight(), g_handle.rows);
    const bool coming = !g_handle.up;
    g_handle.down = hang.down;
    g_handle.cut = hang.cut;
    g_handle.alpha = alpha;
    show(g_handle);
    // Come onto the screen while a bar is on it (the bar's way up): over the bar's shadow, as on the way down.
    if (coming && g_handle.up && g_bar.up) handle_above_bar();
}

LRESULT CALLBACK handle_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // Hidden while the game was held for the minimise: Windows does not bring it back before the overlay does.
    if (system_reshow(g_handle, msg, w, l)) return 0;
    // Clicks go through it to the game; the game's window hears the pointer resting on it.
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    // Lit: whether the pointer is still on it.
    if (msg == WM_TIMER && w == kHandleTimer) {
        handle_update();
        return 0;
    }
    return DefWindowProcW(h, msg, w, l);
}

bool pointer_at_edge() {
    if (asking() || g_pointer_down || g_game_down) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    // The top edge: within the bar's height for the wait's end (the pointer may slip a little lower meanwhile).
    const bool edge = p.x >= a.left && p.x < a.right && p.y >= a.top && p.y < a.top + bar_height();
    const bool handle = g_handle.up && on_handle(p.x - a.left, p.y - a.top);
    if (!edge && !handle) return false;
    // Another window over the game there (another program's, the title bar of none): not the game's edge. The handle
    // lets the pointer through to the game's window, as its clicks.
    return WindowFromPoint(p) == g_game;
}

// ---- the frame behind the glass, and the game's first picture (the UI thread's)

// The overlay's clock for its glass: a window of messages alone, whose timer looks for new reads while a piece is up,
// and which the painter tells of each picture made.
constexpr UINT_PTR kGlassTimer = 5, kWatchTimer = 6, kStatsTimer = 7;
// At most 20 times a second; 15 ms apart while the question waits for its read.
constexpr UINT kGlassMs = 50, kGlassWaitTickMs = 15;
bool g_glass_ticking = false;
UINT g_glass_every = 0;
// Waiting for the game's first picture: the whole frame read (at most every 100 ms) until it is no longer black, from
// the first frame on; when the first frame came. Given up after 20 s, or at once where the frame cannot be read: the
// bar comes down then anyway.
bool g_watch_first = false;
UINT64 g_first_frame_at = 0;
constexpr UINT kWatchMs = 100;
constexpr UINT64 kWatchMostMs = 20000;

// A piece's window grown by the blur's reach, in the game's window.
glass::Rect with_reach(const Shown& s) {
    if (!s.picture) return glass::Rect{0, 0, 0, 0};
    return glass::Rect{s.x - blur_reach(), s.y - blur_reach(), s.picture->w + 2 * blur_reach(), s.picture->h + 2 * blur_reach()};
}

void glass_wish() {
    const int w = area_w(), h = area_h();
    std::vector<glass::Rect> rects;
    // The whole frame for the question, or ahead of it while the X is under the pointer or held, or while the game's
    // first picture is looked for.
    const bool whole = g_asking || (g_bar.up && (g_bar_hover == kQuitChip || g_bar_pressed == kQuitChip)) || g_watch_first;
    if (whole) {
        rects.push_back(glass::Rect{0, 0, w, h});
    } else {
        // The bar's window, down or about to come: the game's width, the bar and its shadow's room.
        if (g_bar.up || g_bar_wanted || g_bar_coming) {
            rects.push_back(glass::Rect{-blur_reach(), -blur_reach(), w + 2 * blur_reach(), bar_height() + px(kRoomBottom) + 2 * blur_reach()});
        }
        // The notice and the counter where their pictures put them (before the first, nothing: it comes bare, then
        // the read for its place).
        if (g_notice_up && g_notice.picture) {
            glass::Rect r = with_reach(g_notice);
            // Its slide's room above its resting place.
            r.y -= px(kSlide);
            r.h += px(kSlide);
            rects.push_back(r);
        }
        if (g_fps_corner && g_reading.shown && g_fps.picture) rects.push_back(with_reach(g_fps));
        // A piece that moved: its new place too, until its picture there has the frame behind it.
        if (g_notice_up && g_notice.moving) rects.push_back(g_notice.next);
        if (g_fps_corner && g_reading.shown && g_fps.moving) rects.push_back(g_fps.next);
    }
    // Rectangles that touch are read as one.
    for (bool merged = true; merged;) {
        merged = false;
        for (std::size_t i = 0; i < rects.size() && !merged; ++i) {
            for (std::size_t j = i + 1; j < rects.size() && !merged; ++j) {
                const glass::Rect& a = rects[i];
                const glass::Rect& b = rects[j];
                if (a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h) {
                    const int x0 = std::min(a.x, b.x), y0 = std::min(a.y, b.y);
                    rects[i] = glass::Rect{x0, y0, std::max(a.x + a.w, b.x + b.w) - x0, std::max(a.y + a.h, b.y + b.h) - y0};
                    rects.erase(rects.begin() + static_cast<std::ptrdiff_t>(j));
                    merged = true;
                }
            }
        }
    }
    // Each within the game's window, on whole quarters (glass::want does that); none while the window is minimised.
    if (g_minimised_hold) rects.clear();
    glass::want(rects, w, h);
    // The clock runs while anything is wanted, or a piece waits for its glass: quicker while the question waits for
    // its read.
    const UINT every = g_ask_waiting ? kGlassWaitTickMs : kGlassMs;
    if (!rects.empty() && g_clock && (!g_glass_ticking || g_glass_every != every)) {
        g_glass_ticking = true;
        g_glass_every = every;
        SetTimer(g_clock, kGlassTimer, every, nullptr);
    } else if (rects.empty() && g_glass_ticking && g_clock) {
        g_glass_ticking = false;
        KillTimer(g_clock, kGlassTimer);
    }
}

// Whether the read shows the game's picture rather than its black start: one in fifty of its quarter pixels, looked at
// sparsely, brighter than black's noise.
bool picture_in(const std::vector<glass::Shot>& shots) {
    for (const glass::Shot& s : shots) {
        if (s.w <= 0 || s.h <= 0) continue;
        int seen = 0, lit = 0;
        // Every 4th quarter pixel each way: 1 in 16 of them, a few thousand at 4K.
        for (int y = 0; y < s.h; y += 4) {
            for (int x = 0; x < s.w; x += 4) {
                const std::uint8_t* p = s.rgba.data() + (static_cast<std::size_t>(y) * static_cast<std::size_t>(s.w) + static_cast<std::size_t>(x)) * 4;
                ++seen;
                if (std::max({p[0], p[1], p[2]}) > 40) ++lit;
            }
        }
        if (seen && lit * 50 >= seen) return true;
    }
    return false;
}

// The game's first picture is up: the bar comes down for a few seconds so that a player sees where it is, and the
// handle shows after it.
void first_picture(const char* how) {
    if (g_first_picture) return;
    g_first_picture = true;
    g_watch_first = false;
    if (g_clock) KillTimer(g_clock, kWatchTimer);
    char line[160];
    std::snprintf(line, sizeof line, "player: the game's first picture is up (%s)", how);
    note(line);
    glass_wish();
    reveal_for(kBarRevealMs, "the game's first picture");
    handle_update();
}

// Each piece wanted on the screen made again over the new read; the painter keeps what did not change.
void glass_redraw() {
    if (g_bar_wanted || g_bar.up || g_bar_coming) order_bar();
    if (g_notice_up) order_notice();
    if (g_fps_corner && g_reading.shown) counter_place();
}

void glass_tick() {
    // A new read: every piece over it.
    if (glass::take(g_shots_seen, g_shots)) {
        g_shots_at = GetTickCount64();
        // The first one said in the log: the glass has the game's frame behind it from now on.
        static bool said = false;
        if (!said) {
            said = true;
            char line[160];
            std::snprintf(line, sizeof line, "player: glass: the first read of the frame behind the overlay came (%zu rectangles, the first %dx%d)",
                          g_shots->size(), g_shots->empty() ? 0 : (*g_shots)[0].rect.w, g_shots->empty() ? 0 : (*g_shots)[0].rect.h);
            note(line);
        }
        // The game's picture looked for in a read of the whole frame.
        if (g_watch_first && holds(*g_shots, glass::Rect{0, 0, area_w(), area_h()}) && picture_in(*g_shots)) first_picture("the frame is no longer black");
        if (!g_asking) glass_redraw();
    }
    if (g_ask_waiting) {
        const UINT64 waited = GetTickCount64() - g_ask_asked;
        // A read of the whole frame since it was asked (one in flight as it was asked holds less).
        const bool read = glass::generation() != g_ask_after && holds(*g_shots, glass::Rect{0, 0, area_w(), area_h()});
        bool done = false;
        if (g_ask_restoring) {
            // After a minimised window: once the game has drawn its picture again, a read of it that shows more than black
            // (where the frame cannot be read, once it has shown a frame); at most kAskRestoreWaitMs, and not while the
            // window is minimised again, where the question would show nowhere.
            const bool drawn = glass::refused() ? g_hooks.frames && g_hooks.frames().count > g_ask_frames : read && picture_in(*g_shots);
            done = drawn || (waited >= kAskRestoreWaitMs && !IsIconic(g_frame));
        } else {
            // The question is made once a read of the whole frame has come, or bare after the wait.
            done = read || waited >= kAskWaitMs || glass::refused();
        }
        if (done) {
            paint_ask();
            // The clock back to its pace.
            glass_wish();
        }
    }
    // Pieces waiting for their glass past the wait show bare; a piece that moved is asked for again (its read, or the
    // end of the wait).
    if (g_bar_wanted && !g_bar.up) bar_frame();
    if (g_fps_corner && g_reading.shown && (!g_fps.up || g_fps.moving)) counter_place();
    if (g_notice_up && g_notice.moving) order_notice();
}

// The pictures the painter made since the last look, each to its piece.
void take_painted() {
    Painted got[kPieces];
    {
        std::lock_guard<std::mutex> l(g_paint_lock);
        for (int i = 0; i < kPieces; ++i) {
            got[i] = std::move(g_painted[i]);
            g_painted[i] = Painted{};
        }
    }
    if (got[kQuestionPiece].ready && g_asking) {
        take(g_ask, got[kQuestionPiece]);
        show_ask();
    }
    if (got[kBarPiece].ready && (g_bar_wanted || g_bar.up || g_bar_coming)) {
        take(g_bar, got[kBarPiece]);
        if (g_bar_wanted || g_bar.up) bar_frame();
    }
    if (got[kNoticePiece].ready && g_notice_up) {
        if (accept(g_notice, got[kNoticePiece])) {
            const bool placed = g_notice.picture != nullptr;
            take(g_notice, got[kNoticePiece]);
            notice_frame();
            // Its first picture says where it goes: the frame behind it is read for that place from now on.
            if (!placed) glass_wish();
        } else {
            // Its new place read first.
            glass_wish();
        }
    }
    if (got[kCounterPiece].ready && g_fps_corner) {
        if (accept(g_fps, got[kCounterPiece])) {
            const bool placed = g_fps.picture != nullptr;
            take(g_fps, got[kCounterPiece]);
            if (g_reading.shown && (g_fps.up || ready(g_fps))) {
                // Its new picture where the bar has it now (the same place on the screen as the one before it).
                g_fps.down = g_fps_corner == 1 || g_fps_corner == 2 ? under_bar(g_fps) : 0;
                show(g_fps);
            }
            if (!placed) glass_wish();
        } else {
            glass_wish();
        }
    }
    if (got[kHandlePiece].ready) {
        take(g_handle, got[kHandlePiece]);
        handle_update();
    }
}

// Every 5 s with the stats on: what the overlay's pictures cost the painter and the UI thread.
void overlay_stats() {
    static std::uint64_t count0 = 0, ns0 = 0, shows0 = 0, show_ns0 = 0;
    const std::uint64_t count = g_paint_count.load(std::memory_order_relaxed), ns = g_paint_ns.load(std::memory_order_relaxed);
    const std::uint64_t most = g_paint_most_ns.exchange(0, std::memory_order_relaxed);
    if (count == count0 && g_show_count == shows0) return;
    char line[300];
    std::snprintf(line, sizeof line,
                  "stats: overlay: %llu pictures made on its painter thread (%.3f ms each, the longest %.3f ms), %llu handed to the windows on the UI thread "
                  "(%.3f ms each, the longest %.3f ms)",
                  static_cast<unsigned long long>(count - count0), count > count0 ? static_cast<double>(ns - ns0) / 1e6 / static_cast<double>(count - count0) : 0.0,
                  static_cast<double>(most) / 1e6, static_cast<unsigned long long>(g_show_count - shows0),
                  g_show_count > shows0 ? static_cast<double>(g_show_ns - show_ns0) / 1e6 / static_cast<double>(g_show_count - shows0) : 0.0,
                  static_cast<double>(g_show_most_ns) / 1e6);
    note(line);
    count0 = count;
    ns0 = ns;
    shows0 = g_show_count;
    show_ns0 = g_show_ns;
    g_show_most_ns = 0;
}

// The watch for the game's first picture: from the first frame on, the whole frame read until it shows a picture; the
// bar comes down at the latest 20 s after the first frame, or at once where the frame cannot be read.
void watch_first() {
    if (g_first_picture || !g_hooks.frames) return;
    if (g_hooks.frames().count == 0) return;
    const UINT64 now = GetTickCount64();
    if (!g_watch_first) {
        g_watch_first = true;
        g_first_frame_at = now;
        glass_wish();
    }
    if (glass::refused()) first_picture("the frame cannot be read here");
    else if (now - g_first_frame_at >= kWatchMostMs) first_picture("no picture brighter than black in 20 s");
}

// ---- the motion's clock, and what a check reads of a motion (the UI thread's, and a thread of the overlay's own)

// While a piece is on a way, the UI thread steps it once for each refresh of the display, never by a timer's fixed
// pace: a thread of the overlay's own, the stepper, waits for the compositor's next pass (the moment a layered
// window's new place is first seen) and posts the clock a message, at most one in its queue at a time, so that a
// busy UI thread drops steps rather than piling them up. A step only places pictures made before (bar_step,
// notice_frame): it costs the UI thread a call or two and the game's render thread nothing.
std::atomic<bool> g_stepping{false}, g_step_posted{false};
HANDLE g_step_wake = nullptr;
constexpr UINT kStepMessage = WM_APP + 2;
// Where the stepper could not be started: the clock window's own timer steps instead, as often as Windows lets it.
constexpr UINT_PTR kStepTimer = 8;

// A check's trace of the motions (PLAYER_TRACE_MOTION=1): every step said in the log with its time, the rows of the bar
// in sight and where the handle hangs; after each way, the same stretch of time again with nothing moving, to compare
// the game's frames with. Without it, with the player's stats on, one line a way.
bool g_trace_motion = false;

// One way as it is watched: which way, when it began, its steps so far, when the last one was and the longest time
// between two; the game's count of frames at its start and at its last step, and the longest time between two frames.
struct Watched {
    bool on = false, down = false;
    std::int64_t began = 0, last = 0, longest = 0, until = 0;
    int steps = 0;
    FrameCount first, seen;
    long long longest_frame = 0;
};
// The bar's way being watched, and the stretch at rest after it (the trace's).
Watched g_way, g_still;

// A step of a watched stretch at `now`: counted, its time since the last one kept if it is the longest, and the game's
// frames since then looked at.
void watch_step(Watched& w, std::int64_t now) {
    ++w.steps;
    // The first step has none before it to be apart from.
    if (w.steps > 1) w.longest = std::max(w.longest, now - w.last);
    w.last = now;
    if (!g_hooks.frames) return;
    const FrameCount count = g_hooks.frames();
    if (count.count > w.seen.count) {
        // The time between the frames shown since the last look, each (one frame as a rule; the mean of several).
        w.longest_frame = std::max(w.longest_frame, (count.ns - w.seen.ns) / static_cast<long long>(count.count - w.seen.count));
        w.seen = count;
    }
}

// A watched stretch begun at `now`: the game's count of frames as it is then.
void watch_begin(Watched& w, std::int64_t now, bool down) {
    w = Watched{};
    w.on = true;
    w.down = down;
    w.began = w.last = now;
    if (g_hooks.frames) w.first = w.seen = g_hooks.frames();
}

// What a watched stretch came to, as the end of a log line: its steps and how far apart they were, and the game's
// frames meanwhile and how far apart those were.
std::string watch_said(const Watched& w, std::int64_t now) {
    const double ms = static_cast<double>(now - w.began) / 1e6;
    const unsigned long long frames = w.seen.count - w.first.count;
    char line[240];
    std::snprintf(line, sizeof line,
                  "%d steps in %.1f ms, %.2f ms apart (the longest %.2f ms); the game showed %llu frames meanwhile, %.2f ms apart (the longest %.2f ms)",
                  w.steps, ms, w.steps > 1 ? ms / (w.steps - 1) : 0.0, static_cast<double>(w.longest) / 1e6, frames,
                  frames ? static_cast<double>(w.seen.ns - w.first.ns) / 1e6 / static_cast<double>(frames) : 0.0, static_cast<double>(w.longest_frame) / 1e6);
    return line;
}

void trace_settled(std::int64_t now);

// A step of the bar's way `way`, for the trace and the stats: a new way watched from its first step (one cut short by
// a turn back is said as it is), and with the trace on, the step said.
void trace_step(const Slide& way, std::int64_t now, float place, int rows) {
    if (!g_trace_motion && !g_hooks.stats) return;
    // At rest with nothing watched: no way to tell of.
    if (!way.moving(now) && !g_way.on) return;
    if (g_way.on && g_way.began != way.began) {
        // Turned back midway: the way so far, then the new one from here.
        note(("player: motion: the bar turned back on its way " + std::string(g_way.down ? "down" : "up") + " after " + watch_said(g_way, now)).c_str());
        g_way.on = false;
    }
    if (!g_way.on) watch_begin(g_way, way.began, way.to > way.from);
    watch_step(g_way, now);
    if (!g_trace_motion) return;
    char line[240];
    std::snprintf(line, sizeof line,
                  "player: motion: step %d at %.2f ms: the bar at %.3f, %d of %d rows; the handle %s, %d down, %d cut, opacity %d; the top pieces %d down",
                  g_way.steps, static_cast<double>(now - g_way.began) / 1e6, static_cast<double>(place), rows, g_bar.rows, g_handle.up ? "up" : "hidden",
                  g_handle.down, g_handle.cut, g_handle.up ? g_handle.alpha : 0, bar_in_sight());
    note(line);
}

// The bar's way is over at `now`: said in a line; with the trace on, the same stretch of time is then watched with
// nothing moving, for the game's frames to be compared.
void trace_settled(std::int64_t now) {
    if (!g_way.on) return;
    g_way.on = false;
    note(("player: motion: the bar " + std::string(g_way.down ? "came down: " : "went up: ") + watch_said(g_way, now)).c_str());
    if (!g_trace_motion) return;
    watch_begin(g_still, now, g_way.down);
    g_still.until = now + (now - g_way.began);
}

// The bar was put away at once at `now` (the window minimised) with a way under way: that way is said as cut short.
void trace_cut(std::int64_t now) {
    if (!g_way.on) return;
    g_way.on = false;
    note(("player: motion: the bar was put away on its way " + std::string(g_way.down ? "down" : "up") + " after " + watch_said(g_way, now)).c_str());
}

// The stepper started (or kept going): from now on a step comes with each refresh, until nothing moves any more.
void motion_start() {
    if (!g_clock) return;
    if (!g_step_wake) {
        // No stepper: the clock window's timer steps.
        SetTimer(g_clock, kStepTimer, USER_TIMER_MINIMUM, nullptr);
        return;
    }
    if (!g_stepping.exchange(true, std::memory_order_acq_rel)) SetEvent(g_step_wake);
}

// One step, on the UI thread: everything on a way placed where it is now; with nothing left on a way, the stepper rests.
void motion_step() {
    // The bar, with the handle and the pieces at the top. On its way up with the pointer come back onto what is left
    // of it, it turns back from where it is (bar_frame sees the pointer); else its next step.
    if (g_bar.up && g_slide.to <= 0.0f && g_slide.moving(now_ns()) && pointer_on_bar()) bar_frame();
    else bar_step();
    // The notice's own slide in and fade out.
    if (g_notice_up && g_notice_stepping) notice_frame();
    const std::int64_t now = now_ns();
    if (g_still.on) {
        // The trace's stretch at rest after a way: steps that move nothing, the game's frames watched as during the way.
        watch_step(g_still, now);
        if (now >= g_still.until || g_slide.moving(now)) {
            g_still.on = false;
            note(("player: motion: at rest after it, nothing moving: " + watch_said(g_still, now)).c_str());
        }
    }
    // The bar on a way until a step has settled it (not by the clock alone: its way's end may fall between a step and
    // this look, and the step that settles it must still come).
    if (g_bar_on_way || (g_notice_up && g_notice_stepping) || g_still.on) return;
    // Nothing on a way: no more steps until a way begins.
    g_stepping.store(false, std::memory_order_release);
    KillTimer(g_clock, kStepTimer);
}

// The stepper's thread: asleep until a way begins, then a message to the clock at each refresh until none is left.
void stepper_loop() {
    // The compositor's wait for its next pass, looked up in System32 rather than linked (the player starts wherever
    // it did, as with the title bar's colours).
    using Flush = HRESULT(WINAPI*)();
    Flush flush = nullptr;
    if (HMODULE dwm = LoadLibraryExW(L"dwmapi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32)) flush = reinterpret_cast<Flush>(GetProcAddress(dwm, "DwmFlush"));
    // A timer finer than the system's tick, for where the compositor gives no pace.
    HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    for (;;) {
        WaitForSingleObject(g_step_wake, INFINITE);
        // The waits in a row that came back at once: three, and the compositor is taken not to wait at all here.
        int quick = 0;
        while (g_stepping.load(std::memory_order_acquire)) {
            const std::int64_t before = now_ns();
            if (flush && quick < 3 && SUCCEEDED(flush())) {
                // Back within half a millisecond: just before a pass, once; again and again, no wait at all.
                quick = now_ns() - before < 500000 ? quick + 1 : 0;
            } else {
                // No pace from the compositor: the display's own interval as the window knows it (a sixtieth of a
                // second where it does not), on the finer timer or, without one, by the system's sleep.
                std::int64_t interval = g_hooks.refresh_ns ? g_hooks.refresh_ns() : 0;
                if (interval <= 0) interval = 16666667;
                LARGE_INTEGER due;
                // Relative, in 100 ns units.
                due.QuadPart = -std::max<long long>(1, interval / 100);
                if (timer && SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE)) WaitForSingleObject(timer, 100);
                else Sleep(static_cast<DWORD>(std::max<std::int64_t>(1, interval / 1000000)));
            }
            // One step in the UI thread's queue at a time.
            if (!g_step_posted.exchange(true, std::memory_order_acq_rel)) PostMessageW(g_clock, kStepMessage, 0, 0);
        }
    }
}

LRESULT CALLBACK clock_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_TIMER && w == kGlassTimer) {
        glass_tick();
        return 0;
    }
    if (msg == WM_TIMER && w == kWatchTimer) {
        watch_first();
        return 0;
    }
    if (msg == WM_TIMER && w == kStatsTimer) {
        overlay_stats();
        return 0;
    }
    if (msg == kPaintedMessage) {
        take_painted();
        return 0;
    }
    if (msg == kStepMessage || (msg == WM_TIMER && w == kStepTimer)) {
        // The stepper may post its next one from now on.
        g_step_posted.store(false, std::memory_order_release);
        motion_step();
        return 0;
    }
    return DefWindowProcW(h, msg, w, l);
}

// ---- the cursor

// The pointer over the game: a dart, its tip the hot spot, in the logo's look: the left face chrome (a silver that darkens
// downwards), the right face the lime of its Q, a dark rim around both that keeps it seen on the game's light and green
// parts, and a soft shadow under it. Pressed (the mouse's finger down on the game), both faces turn lime and the dart is a
// little smaller, as if pressed into the screen. Drawn for a canvas of `size` pixels (32 at 96 dpi).
HCURSOR make_cursor(int size, bool pressed) {
    const float k = size / 32.0f;
    // The dart at 32 pixels: symmetric along its axis (the tip, a wing either side, the notch between them on the axis),
    // leaned 22.5 degrees so that its left edge stands upright, as a pointer's does.
    const float h = pressed ? 20.0f : 22.0f, half = pressed ? 7.8f : 8.6f, notch = pressed ? 5.6f : 6.2f;
    const float lean = 22.5f * 3.14159265f / 180.0f, tip = 3.2f;
    auto at = [&](float x, float y) {
        return PointF((x * std::cos(lean) + y * std::sin(lean) + tip) * k, (-x * std::sin(lean) + y * std::cos(lean) + tip) * k);
    };
    const PointF t = at(0, 0), left = at(-half, h), mid = at(0, h - notch), right = at(half, h);
    const PointF dart[] = {t, left, mid, right};
    const PointF left_face[] = {t, left, mid}, right_face[] = {t, mid, right};
    const float top = t.Y, bottom = std::max(left.Y, right.Y);
    Canvas c(size, size);
    {
        auto bmp = c.surface();
        Graphics g(bmp.get());
        g.SetSmoothingMode(SmoothingModeAntiAlias);
        g.SetPixelOffsetMode(PixelOffsetModeHalf);
        // The shadow: the dart a little down and to the right, soft at its edge.
        GraphicsPath shadow;
        shadow.AddPolygon(dart, 4);
        Matrix down;
        down.Translate(1.0f * k, 1.6f * k);
        shadow.Transform(&down);
        Pen soft(Color(40, 0, 0, 0), 2.4f * k);
        soft.SetLineJoin(LineJoinRound);
        g.DrawPath(&soft, &shadow);
        SolidBrush shade(Color(90, 0, 0, 0));
        g.FillPath(&shade, &shadow);
        // The rim: wider than what the faces leave of it, a thin dark line outside them.
        GraphicsPath outline;
        outline.AddPolygon(dart, 4);
        Pen rim(Color(255, 7, 9, 12), 3.2f * k);
        rim.SetLineJoin(LineJoinRound);
        g.DrawPath(&rim, &outline);
        // The faces, each a gradient from the tip's height to the wings'.
        const PointF from(0, top), to(0, bottom + 0.01f);
        LinearGradientBrush chrome(from, to, pressed ? Color(255, 214, 255, 160) : Color(255, 250, 252, 255),
                                   pressed ? Color(255, 150, 240, 70) : Color(255, 150, 160, 172));
        LinearGradientBrush lime(from, to, pressed ? Color(255, 120, 215, 50) : Color(255, 165, 250, 85),
                                 pressed ? Color(255, 60, 150, 22) : Color(255, 80, 175, 28));
        chrome.SetWrapMode(WrapModeTileFlipXY);
        lime.SetWrapMode(WrapModeTileFlipXY);
        g.FillPolygon(&chrome, left_face, 3);
        g.FillPolygon(&lime, right_face, 3);
    }
    // CreateIconIndirect wants its bitmaps out of any device context.
    SelectObject(c.dc, c.old);
    std::vector<BYTE> zeros(static_cast<std::size_t>((size + 15) / 16 * 2 * size), 0);
    HBITMAP mask = CreateBitmap(size, size, 1, 1, zeros.data());
    // The hot spot: the dart's tip.
    const auto hot = static_cast<DWORD>(std::lround(tip * k));
    ICONINFO info{FALSE, hot, hot, mask, c.bitmap};
    HCURSOR cursor = CreateIconIndirect(&info);
    DeleteObject(mask);
    // Without one (Windows refused it), Windows' own arrow: a pointer all the same.
    return cursor ? cursor : LoadCursorA(nullptr, IDC_ARROW);
}

}  // namespace

void start(HWND frame, HWND game, const Hooks& hooks, bool korean) {
    g_frame = frame;
    g_game = game;
    g_hooks = hooks;
    g_korean = korean;
    GdiplusStartupInput input;
    GdiplusStartup(&g_gdiplus, &input, nullptr);
    // The player's own faces and the wordmark's pictures, from its folder (Windows' own faces, and the name in words,
    // where they are not there), before the painter draws with them.
    const bool own_faces = load_fonts();
    load_art();
    // Which face the words are drawn in, said once: a log shows at a glance a player whose own faces did not load.
    {
        char line[200];
        std::snprintf(line, sizeof line, "player: the overlay's words are drawn in %s%s", words_face(Weight::kRegular, g_korean).c_str(),
                      own_faces ? "" : " (Windows' own: no Pretendard in fonts beside the player)");
        note(line);
    }
    // The notice, the frame counter and the handle let clicks through to the game; the bar and the question take
    // theirs. The counter first, so that the windows made after it are above it; the handle after the bar, above it:
    // on the bar's way it hangs from the bar's foot, over the bar's shadow, never under it; the question above all.
    g_fps.window = make_window(L"OpenDMTQFrameCounter", fps_proc, true);
    g_notice.window = make_window(L"OpenDMTQNotice", notice_proc, true);
    g_bar.window = make_window(L"OpenDMTQBar", bar_proc, false);
    g_handle.window = make_window(L"OpenDMTQBarHandle", handle_proc, true);
    g_ask.window = make_window(L"OpenDMTQQuestion", ask_proc, false);
    // The glass's clock: a window for messages alone, never on the screen.
    WNDCLASSEXW c{};
    c.cbSize = sizeof c;
    c.lpfnWndProc = clock_proc;
    c.hInstance = GetModuleHandleW(nullptr);
    c.lpszClassName = L"OpenDMTQGlassClock";
    RegisterClassExW(&c);
    g_clock = CreateWindowExW(0, c.lpszClassName, L"", 0, 0, 0, 0, 0, HWND_MESSAGE, nullptr, c.hInstance, nullptr);
    // The painter, for the player's life.
    std::thread(painter_loop).detach();
    // The stepper, likewise: asleep until something is on a way.
    g_step_wake = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (g_step_wake) std::thread(stepper_loop).detach();
    // A check's trace of the motions.
    if (const char* trace = std::getenv("PLAYER_TRACE_MOTION")) g_trace_motion = *trace && *trace != '0';
    // The game's first picture looked for from its first frame.
    if (g_clock) SetTimer(g_clock, kWatchTimer, kWatchMs, nullptr);
    // What the pictures cost, every five seconds, with the stats on.
    if (g_clock && g_hooks.stats) SetTimer(g_clock, kStatsTimer, 5000, nullptr);
}

void notice(const std::string& text, bool live) {
    if (!g_notice.window) return;
    g_notice_text = text;
    g_notice_live = live;
    // From its first step, sliding in, once its picture has come; the one shown before goes.
    g_notice_shown = 0;
    g_notice_stepping = false;
    g_notice_drop = 0;
    if (g_notice.up) hide(g_notice);
    g_notice.picture.reset();
    g_notice.key.clear();
    g_notice_up = true;
    g_notice.wanted = GetTickCount64();
    order_notice();
    // The handle goes while it is up; the frame behind it wanted once its place is known.
    handle_update();
    glass_wish();
    SetTimer(g_notice.window, kNoticeTimer, 15, nullptr);
}

void pointer_moved(int x, int y, bool pressed) {
    g_pointer_down = pressed;
    // The handle lights while the pointer is on its reach with no button down, and goes back as it leaves.
    if (g_handle.up && (on_handle(x, y) && !pressed) != g_handle_lit) handle_update();
    // A move message to where the pointer already was (Windows sends some after a click) is no move: a rest only counts
    // when the pointer came to it by moving.
    const bool moved = x != g_moved_x || y != g_moved_y;
    g_moved_x = x;
    g_moved_y = y;
    // Not while the mouse plays (its button down), not over the question, and only at the very top edge of the game
    // (within 4 pixels at 720 lines) or on the handle: the game's own controls under the bar's place stay the game's
    // while they are used.
    if (!g_bar.window || asking() || pressed) {
        rest_cancel();
        return;
    }
    if (!moved) return;
    // A mouse's move: the pointer is the mouse's again.
    g_bar_by_touch = false;
    const bool edge = y < std::max(1, px(4));
    const bool handle = g_handle.up && on_handle(x, y);
    if (!edge && !handle) {
        // Moved away from the edge and the handle: no rest there.
        if (g_rest_armed) rest_cancel();
        return;
    }
    // Down already: it stays. Else the pointer waits a moment, and the bar comes only if it rests there then, with the
    // game quiet (no press) for kQuietMs.
    if (g_bar.up) {
        reveal(kBarStayMs, nullptr);
    } else {
        g_bar_why = handle ? "the pointer on the handle" : "the pointer at the top edge";
        g_rest_armed = true;
        SetTimer(g_bar.window, kBarEdgeTimer, kBarEdgeMs, nullptr);
        // The frame behind the bar read during the wait, and its picture made meanwhile.
        if (!g_bar_coming) {
            g_bar_coming = true;
            glass_wish();
            order_bar();
        }
    }
}

void game_pressed(bool down) {
    // A press or a release on the game: the game is played, and no rest at the edge or on the handle brings the bar
    // until the pointer moves there again with the game quiet.
    g_game_down = down;
    g_game_pressed = GetTickCount64();
    rest_cancel();
}

bool game_quiet() { return !g_game_down && GetTickCount64() - g_game_pressed >= kQuietMs; }

void show_bar() {
    if (!g_bar.window || asking()) return;
    // A finger has no pointer that stays on the bar: whole for a few seconds, then fading.
    g_bar_by_touch = true;
    reveal(kBarTouchStayMs, "a finger from the top edge");
}

bool asking() { return g_ask.window && g_asking; }

void ask_quit() {
    if (!g_ask.window || g_asking) return;
    g_asking = true;
    // The keys pressed on the game let go now, while the game may still go on for a few frames before it is held.
    if (g_hooks.question) g_hooks.question();
    // Keep playing chosen first, so that Enter at once goes on; nothing lit until the pointer moves over it.
    g_choice = kKeep;
    g_ask_hover = kNone;
    g_ask_pressed = kNone;
    // Over a minimised window it would show nowhere, and the game drew nothing while it was held there: the window
    // comes back first, and the game goes on until it has drawn its picture again (a frame or a few; mid-song on its own
    // pause screen, where the song waits), then holds, and the question shows over that picture.
    g_ask_restoring = IsIconic(g_frame) || g_minimised_hold;
    g_ask_frames = g_hooks.frames ? g_hooks.frames().count : 0;
    // A read of the whole frame the X had made ahead (under the pointer a moment ago) is taken at once; else one is
    // asked for now, and the question is made when it comes (a few frames) or bare after kAskWaitMs. The game goes on
    // meanwhile, so that the read has a frame to read. After a minimised window no read is fresh: the game drew nothing.
    if (glass::take(g_shots_seen, g_shots)) g_shots_at = GetTickCount64();
    const bool fresh = !g_ask_restoring && holds(*g_shots, glass::Rect{0, 0, area_w(), area_h()}) && GetTickCount64() - g_shots_at < kAskFreshMs;
    // Where the frame cannot be read there is no read to wait for, but after a minimised window still a frame.
    g_ask_waiting = !fresh && (g_ask_restoring || !glass::refused());
    g_ask_ahead = fresh;
    g_ask_after = glass::generation();
    g_ask_asked = GetTickCount64();
    // The bar goes up from where it is (its chips take no press meanwhile); one only wanted so far never comes.
    bar_frame();
    handle_update();
    // Back from minimised: the window lets the game go on as it comes back (minimised(false)), the question waiting.
    if (IsIconic(g_frame)) ShowWindow(g_frame, SW_RESTORE);
    glass_wish();
    if (!g_ask_waiting) paint_ask();
}

void minimised(bool now) {
    if (now) {
        // Minimised mid-song: the game holds still as a phone's does when its owner leaves it; the bar goes with it.
        g_minimised_hold = true;
        hide_bar();
    } else {
        // Back: the game goes on (to its own pause screen mid-song), unless the question is up.
        g_minimised_hold = false;
        // Back while the question waits for the game's picture (asked over the minimised window, or minimised again
        // meanwhile): its wait, and the frames it waits for, from now.
        if (g_asking && g_ask_waiting && g_ask_restoring) {
            g_ask_asked = GetTickCount64();
            g_ask_after = glass::generation();
            g_ask_frames = g_hooks.frames ? g_hooks.frames().count : 0;
        }
    }
    update_hold();
    glass_wish();
}

bool ask_key(UINT vk) {
    if (!asking()) return false;
    if (vk == VK_LEFT || vk == VK_RIGHT || vk == VK_TAB) {
        // Two buttons side by side: each of these keys moves the choice to the other.
        g_choice = g_choice == kKeep ? kQuit : kKeep;
        draw_ask();
    } else if (vk == VK_RETURN) {
        answer(g_choice == kQuit);
    } else if (vk == VK_ESCAPE) {
        // Esc is keep playing, as the thin X is.
        answer(false);
    }
    // Every other key waits while the question is up.
    return true;
}

void place() {
    // The question over the game's area as it is now: made again for a new size, moved with the window.
    if (asking() && !g_ask_waiting) {
        if (g_ask.up) show(g_ask);
        draw_ask();
    }
    // The bar across the game's top at its new width, if it is down.
    if (g_bar.up || g_bar_wanted) bar_frame();
    if (g_notice_up) notice_frame();
    // The frame counter in its corner, at the new scale (a move counts nothing: its numbers stay its timer's).
    counter_place();
    handle_update();
    // The frame behind them, where they are now.
    glass_wish();
}

void switched() {
    // The bar comes down for a few seconds after a switch, its chip the other way, so that a player sees where it went
    // (whatever the pointer does meanwhile: one that leaves the bar after the chip's click does not take it up sooner);
    // not before the game's first picture (the start switches to full screen before anything shows).
    if (!g_first_picture) return;
    reveal_for(kBarRevealMs, full_screen() ? "full screen" : "a window");
}

void show_fps(int corner) {
    if (!g_fps.window || corner <= 0 || corner > 4 || !g_hooks.frames) return;
    g_fps_corner = corner;
    // Hidden until the game's first frame, then measured: looked at ten times a second until then.
    fps_look_now();
}

HCURSOR cursor(bool pressed) {
    static std::map<std::pair<int, bool>, HCURSOR> made;
    // Windows' own cursor size at this scale: 32 pixels at 96 dpi, 48 at 150 % (Windows' scale alone, as its own
    // pointer's).
    const int size = std::max(32, static_cast<int>(std::lround(32 * window_dpi())));
    HCURSOR& c = made[{size, pressed}];
    if (!c) c = make_cursor(size, pressed);
    return c;
}

#ifdef OVERLAY_TEST_HOOKS
namespace {

// A PNG of a premultiplied picture, with its own alpha, times `opacity` (its window's, 255: none).
void save_png(Canvas& c, const std::wstring& path, BYTE opacity = 255) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    std::unique_ptr<Canvas> faded;
    Canvas* from = &c;
    if (opacity != 255 && c.bits) {
        // The window's opacity on every byte of the premultiplied picture, as UpdateLayeredWindow lays it over the game.
        faded = std::make_unique<Canvas>(c.w, c.h);
        if (faded->bits) {
            const auto* src = static_cast<const std::uint8_t*>(c.bits);
            auto* dst = static_cast<std::uint8_t*>(faded->bits);
            for (std::size_t i = 0; i < static_cast<std::size_t>(c.w) * static_cast<std::size_t>(c.h) * 4; ++i) {
                dst[i] = static_cast<std::uint8_t>((src[i] * opacity + 127) / 255);
            }
            from = faded.get();
        }
    }
    Bitmap out(from->w, from->h, PixelFormat32bppARGB);
    Graphics g(&out);
    g.Clear(Color(0, 0, 0, 0));
    g.SetCompositingMode(CompositingModeSourceCopy);
    auto picture = from->surface();
    g.DrawImage(picture.get(), 0, 0, from->w, from->h);
    out.Save(path.c_str(), &png, nullptr);
}

// How long the painter takes to make a piece's picture over a new frame behind it (the frame's blur and tint, the
// glass, its words over it), in milliseconds, the mean of a few: "time <name> <ms>" in the layout file.
void time_line(FILE* out, const char* name, Paint& p, const std::vector<glass::Shot>& shots) {
    LARGE_INTEGER f{}, a{}, b{};
    QueryPerformanceFrequency(&f);
    constexpr int kRuns = 5;
    QueryPerformanceCounter(&a);
    for (int i = 0; i < kRuns; ++i) {
        // As if a new read had come: the frame behind blurred again and the picture made again.
        p.have_backdrop = false;
        p.backdrop_from = 0;
        p.drawn_serial = -1;
        paint_draw(p, shots);
    }
    QueryPerformanceCounter(&b);
    if (out) std::fprintf(out, "time %s %.3f\n", name, static_cast<double>(b.QuadPart - a.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart) / kRuns);
}

// A name of ASCII letters from wide to narrow.
std::string narrow_ascii(const std::wstring& s) {
    std::string out;
    for (wchar_t c : s) out += static_cast<char>(c);
    return out;
}

// The game's frame as the probe has it: RGBA bytes, top row first, the game's area's size.
std::vector<std::uint8_t> g_test_frame;
int g_test_frame_w = 0, g_test_frame_h = 0;

// What the render thread would read of the frame, as a read of the whole frame: at a quarter of its size as its blit
// makes it (glass_capture.cpp's read: a pass to half the size then one to a quarter, each a linear filter at exactly
// half, so that each quarter pixel is the mean of its 4 by 4). Every wanted rectangle starts on the window's multiples
// of 4, so one read of the whole frame holds the same pixels as the pieces' own reads would: the probe reads that one.
std::shared_ptr<const std::vector<glass::Shot>> test_read() {
    const int w = g_test_frame_w, h = g_test_frame_h;
    const glass::Rect r = glass::aligned(glass::Rect{0, 0, w, h}, 0, w, h);
    auto shots = std::make_shared<std::vector<glass::Shot>>();
    glass::Shot s;
    s.rect = r;
    s.w = r.w / 4;
    s.h = r.h / 4;
    s.rgba.resize(static_cast<std::size_t>(s.w) * static_cast<std::size_t>(s.h) * 4);
    for (int j = 0; j < s.h; ++j) {
        for (int i = 0; i < s.w; ++i) {
            for (int c = 0; c < 4; ++c) {
                // The half pass: each half pixel the mean of its 2 by 2 (rounded as a GPU's 8-bit target keeps it),
                // then the quarter pass the mean of 2 by 2 of those.
                int halves[4];
                for (int hy = 0; hy < 2; ++hy) {
                    for (int hx = 0; hx < 2; ++hx) {
                        int sum = 0;
                        for (int dy = 0; dy < 2; ++dy) {
                            for (int dx = 0; dx < 2; ++dx) {
                                const int x = std::min(w - 1, r.x + i * 4 + hx * 2 + dx), y = std::min(h - 1, r.y + j * 4 + hy * 2 + dy);
                                sum += g_test_frame[(static_cast<std::size_t>(y) * static_cast<std::size_t>(w) + static_cast<std::size_t>(x)) * 4 +
                                                    static_cast<std::size_t>(c)];
                            }
                        }
                        halves[hy * 2 + hx] = (sum + 2) / 4;
                    }
                }
                s.rgba[(static_cast<std::size_t>(j) * static_cast<std::size_t>(s.w) + static_cast<std::size_t>(i)) * 4 + static_cast<std::size_t>(c)] =
                    static_cast<std::uint8_t>((halves[0] + halves[1] + halves[2] + halves[3] + 2) / 4);
            }
        }
    }
    shots->push_back(std::move(s));
    return shots;
}

// The game's frame from a PNG into the probe's copy of it; false (and a word on stderr) when it is not there or not of
// the game's area's size.
bool test_frame(const std::wstring& frame_png) {
    Bitmap frame(frame_png.c_str());
    if (frame.GetLastStatus() != Ok || static_cast<int>(frame.GetWidth()) != area_w() || static_cast<int>(frame.GetHeight()) != area_h()) {
        std::fprintf(stderr, "probe: the frame is not there or not the game area's size (%dx%d)\n", area_w(), area_h());
        return false;
    }
    g_test_frame_w = area_w();
    g_test_frame_h = area_h();
    g_test_frame.assign(static_cast<std::size_t>(g_test_frame_w) * static_cast<std::size_t>(g_test_frame_h) * 4, 0);
    BitmapData data{};
    Rect all(0, 0, g_test_frame_w, g_test_frame_h);
    if (frame.LockBits(&all, ImageLockModeRead, PixelFormat32bppARGB, &data) != Ok) return false;
    for (int y = 0; y < g_test_frame_h; ++y) {
        const auto* row = static_cast<const std::uint8_t*>(data.Scan0) + static_cast<std::ptrdiff_t>(y) * data.Stride;
        for (int x = 0; x < g_test_frame_w; ++x) {
            // BGRA as GDI+ holds it, to the RGBA a read gives.
            std::uint8_t* q = g_test_frame.data() + (static_cast<std::size_t>(y) * static_cast<std::size_t>(g_test_frame_w) + static_cast<std::size_t>(x)) * 4;
            q[0] = row[x * 4 + 2];
            q[1] = row[x * 4 + 1];
            q[2] = row[x * 4 + 0];
            q[3] = 255;
        }
    }
    frame.UnlockBits(&data);
    return true;
}

// A piece's picture laid over a copy of the game's frame (RGBA, w by h) as its window lies over the game: its top left
// at (x, y) of the game's area, without its top `cut` rows, at `alpha` as a whole (what show() asks of the window).
void lay_over(std::vector<std::uint8_t>& rgba, int w, int h, const Canvas& picture, int x, int y, int cut, BYTE alpha) {
    const auto* from = static_cast<const std::uint8_t*>(picture.bits);
    for (int row = std::max(0, cut); row < picture.h; ++row) {
        // The picture's row `cut` is the window's first.
        const int ty = y + row - cut;
        if (ty < 0 || ty >= h) continue;
        for (int col = 0; col < picture.w; ++col) {
            const int tx = x + col;
            if (tx < 0 || tx >= w) continue;
            // Premultiplied BGRA, as the window takes it: over the frame, times the window's opacity.
            const std::uint8_t* p = from + (static_cast<std::size_t>(row) * static_cast<std::size_t>(picture.w) + static_cast<std::size_t>(col)) * 4;
            const float whole = static_cast<float>(alpha) / 255.0f, keep = 1.0f - static_cast<float>(p[3]) / 255.0f * whole;
            std::uint8_t* q = rgba.data() + (static_cast<std::size_t>(ty) * static_cast<std::size_t>(w) + static_cast<std::size_t>(tx)) * 4;
            for (int c = 0; c < 3; ++c) {
                q[c] = static_cast<std::uint8_t>(std::lround(std::min(255.0f, static_cast<float>(p[2 - c]) * whole + static_cast<float>(q[c]) * keep)));
            }
        }
    }
}

// The top `rows` rows of an RGBA picture (w across) as a PNG.
void save_rows(const std::vector<std::uint8_t>& rgba, int w, int rows, const std::wstring& path) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    Bitmap out(w, rows, PixelFormat32bppARGB);
    BitmapData data{};
    Rect all(0, 0, w, rows);
    if (out.LockBits(&all, ImageLockModeWrite, PixelFormat32bppARGB, &data) != Ok) return;
    for (int y = 0; y < rows; ++y) {
        auto* row = static_cast<std::uint8_t*>(data.Scan0) + static_cast<std::ptrdiff_t>(y) * data.Stride;
        for (int x = 0; x < w; ++x) {
            // RGBA to the BGRA GDI+ holds.
            const std::uint8_t* q = rgba.data() + (static_cast<std::size_t>(y) * static_cast<std::size_t>(w) + static_cast<std::size_t>(x)) * 4;
            row[x * 4 + 0] = q[2];
            row[x * 4 + 1] = q[1];
            row[x * 4 + 2] = q[0];
            row[x * 4 + 3] = 255;
        }
    }
    out.UnlockBits(&data);
    out.Save(path.c_str(), &png, nullptr);
}

// One line of the layout file: a piece's picture's name and its window's place and size in the game's area.
void layout_line(FILE* out, const char* name, int x, int y, const Canvas* c) {
    if (out) std::fprintf(out, "%s %d %d %d %d\n", name, x, y, c ? c->w : 0, c ? c->h : 0);
}

// The words the last look drew, in the game's area (its window at (x, y)): "text <picture> x y w h rrggbb" a line; then
// a fresh list for the next.
std::vector<TestText> g_test_words;
void words_lines(FILE* out, const std::string& name, int x, int y) {
    for (const TestText& t : g_test_words) {
        if (out) {
            // " cut" after the colour when the words did not fit their box.
            std::fprintf(out, "text %s %.1f %.1f %.1f %.1f %02x%02x%02x%s\n", name.c_str(), t.box.X + static_cast<float>(x), t.box.Y + static_cast<float>(y),
                         t.box.Width, t.box.Height, t.colour.GetR(), t.colour.GetG(), t.colour.GetB(), t.cut ? " cut" : "");
        }
    }
    g_test_words.clear();
}

}  // namespace

void test_save(const std::wstring& prefix, const std::wstring& frame_png, bool with_words) {
    g_test_quiet = true;
    g_test_no_words = !with_words;
    // The frame behind, as the window would show it: of the game's area's size exactly.
    if (!test_frame(frame_png)) return;
    // The view the probe draws for: the game's area, the scale it set, the bar up.
    View base;
    base.w = g_test_frame_w;
    base.h = g_test_frame_h;
    base.dpi = window_dpi();
    const auto shots = test_read();
    const Drawing drawing(base);
    FILE* layout = _wfopen((prefix + L"layout.txt").c_str(), L"w");
    if (layout) std::fprintf(layout, "area 0 0 %d %d\nscale %.4f\n", area_w(), area_h(), static_cast<double>(scale()));
    // The bar in a window and in full screen (its chip's icon the other way), at rest, with each chip lit, and each held.
    for (bool full : {false, true}) {
        const std::wstring state = full ? L"full" : L"window";
        struct BarLook {
            int hover, pressed;
            const wchar_t* suffix;
        };
        for (const BarLook& b : {BarLook{kNone, kNone, L""}, BarLook{kScreenChip, kNone, L"-screen"}, BarLook{kQuitChip, kNone, L"-quit"},
                                 BarLook{kMinChip, kNone, L"-min"}, BarLook{kScreenChip, kScreenChip, L"-screen-pressed"},
                                 BarLook{kQuitChip, kQuitChip, L"-quit-pressed"}, BarLook{kMinChip, kMinChip, L"-min-pressed"}}) {
            Order o;
            o.view = base;
            o.view.full = full;
            o.shots = shots;
            o.hover = b.hover;
            o.pressed = b.pressed;
            o.key = "probe bar " + narrow_ascii(state + b.suffix);
            Paint p;
            g_test_texts = &g_test_words;
            Painted got = paint_bar(o, p);
            g_test_texts = nullptr;
            if (!got.picture) continue;
            save_png(*got.picture, prefix + L"bar-" + state + b.suffix + L".png");
            if (!full && b.hover == kNone) {
                layout_line(layout, "bar", got.x, got.y, got.picture.get());
                // Where its name (the wordmark) went, which the chips keep clear of.
                if (layout) std::fprintf(layout, "bar-name %.1f %.1f %.1f %.1f\n", g_test_bar_name.X, g_test_bar_name.Y, g_test_bar_name.Width, g_test_bar_name.Height);
                // Whether the frame was behind it (else its bare tint): a read must hold it at every size.
                if (layout) std::fprintf(layout, "glass bar %d\n", got.glass ? 1 : 0);
                const Drawing d(o.view);
                time_line(layout, "bar", p, *shots);
            }
            words_lines(layout, "bar-" + std::string(full ? "full" : "window") + narrow_ascii(b.suffix), got.x, got.y);
        }
    }
    // The notice while live and once ended, in the server's own words (server/game/live/state.php), a server's name in
    // its place; a long name, which the card wraps within the game's width; each without the bar and under it; and the
    // long one beside a counter in either top corner.
    const std::string live_text = g_korean ? "이 플레이를 방송하고 있어요\nMy Server 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Broadcasting your play\nWatch it now or later under LIVE on My Server";
    const std::string ended_text = g_korean ? "방송을 마쳤어요\nMy Server 사이트 LIVE에서 다시 볼 수 있어요"
                                            : "Your broadcast has ended\nWatch the replay under LIVE on My Server";
    const std::string long_text = g_korean ? "이 플레이를 방송하고 있어요\nOpenDMTQ Community Server Seoul Central 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Broadcasting your play\nWatch it now or later under LIVE on OpenDMTQ Community Server Seoul Central";
    struct NoticeCase {
        const char* name;
        const std::string* text;
        bool live, bar;
        int corner;
    };
    for (const NoticeCase& n : {NoticeCase{"notice-live", &live_text, true, false, 0}, NoticeCase{"notice-ended", &ended_text, false, false, 0},
                                NoticeCase{"notice-long", &long_text, true, false, 0}, NoticeCase{"notice-live-bar", &live_text, true, true, 0},
                                NoticeCase{"notice-long-fps1", &long_text, true, false, 1}, NoticeCase{"notice-long-fps2", &long_text, true, false, 2}}) {
        Order o;
        o.view = base;
        if (n.bar) o.view.top_room = bar_height();
        o.shots = shots;
        o.text = *n.text;
        o.live = n.live;
        o.corner = n.corner;
        o.key = std::string("probe ") + n.name;
        Paint p;
        g_test_texts = &g_test_words;
        Painted got = paint_notice(o, p);
        g_test_texts = nullptr;
        if (!got.picture) continue;
        save_png(*got.picture, prefix + wide(n.name) + L".png");
        layout_line(layout, n.name, got.x, got.y, got.picture.get());
        words_lines(layout, n.name, got.x, got.y);
        if (layout) std::fprintf(layout, "glass %s %d\n", n.name, got.glass ? 1 : 0);
        if (std::string(n.name) == "notice-live") {
            const Drawing d(o.view);
            time_line(layout, "notice", p, *shots);
        }
    }
    // The frame counter in each corner, at 240 frames a second, at its window's opacity; at the top, with the bar down as
    // well; and its other numbers at the top left, its own place.
    for (int corner = 1; corner <= 4; ++corner) {
        for (bool bar : {false, true}) {
            if (bar && corner > 2) continue;
            Order o;
            o.view = base;
            if (bar) o.view.top_room = bar_height();
            o.shots = shots;
            o.corner = corner;
            o.fps = 240;
            o.ms = 4.2f;
            char name[32];
            std::snprintf(name, sizeof name, "fps%d%s", corner, bar ? "-bar" : "");
            o.key = std::string("probe ") + name;
            Paint p;
            g_test_texts = &g_test_words;
            Painted got = paint_counter(o, p);
            g_test_texts = nullptr;
            if (!got.picture) continue;
            save_png(*got.picture, prefix + wide(name) + L".png", kCounterAlpha);
            layout_line(layout, name, got.x, got.y, got.picture.get());
            words_lines(layout, name, got.x, got.y);
            if (layout) std::fprintf(layout, "glass %s %d\n", name, got.glass ? 1 : 0);
            if (corner == 1 && !bar) {
                const Drawing d(o.view);
                time_line(layout, "fps", p, *shots);
                // Its window's opacity, for the checks that lay it over the frame.
                if (layout) std::fprintf(layout, "opacity fps %d\n", kCounterAlpha);
            }
        }
    }
    struct Count {
        int fps;
        float ms;
        const char* name;
    };
    for (const Count& n : {Count{-1, 0, "fps-dash"}, Count{0, 0, "fps-0"}, Count{60, 16.7f, "fps-60"}, Count{999, 1.0f, "fps-999"}}) {
        Order o;
        o.view = base;
        o.shots = shots;
        o.corner = 1;
        o.fps = n.fps;
        o.ms = n.ms;
        o.key = std::string("probe ") + n.name;
        Paint p;
        g_test_texts = &g_test_words;
        Painted got = paint_counter(o, p);
        g_test_texts = nullptr;
        if (!got.picture) continue;
        save_png(*got.picture, prefix + wide(n.name) + L".png", kCounterAlpha);
        layout_line(layout, n.name, got.x, got.y, got.picture.get());
        words_lines(layout, n.name, got.x, got.y);
    }
    // The handle, at its place: at rest, and lit (the pointer on it).
    for (const bool lit : {false, true}) {
        Order o;
        o.view = base;
        o.shots = shots;
        o.key = lit ? "probe handle lit" : "probe handle";
        o.lit = lit;
        Paint p;
        Painted got = paint_handle(o, p);
        if (!got.picture) continue;
        save_png(*got.picture, prefix + (lit ? L"handle-lit.png" : L"handle.png"));
        // Each at its own place: lit, its window is wider (its rail is longer) and deeper.
        layout_line(layout, lit ? "handle-lit" : "handle", got.x, got.y, got.picture.get());
        if (lit) continue;
        // The reach a resting pointer lights it from, a row at a time: the row, its first place and its last (its rows
        // run from the top edge down without a gap, so the first row with none ends it).
        for (int y = 0; layout; ++y) {
            int first = -1, last = -1;
            for (int x = 0; x < area_w(); ++x) {
                if (!in_handle_reach(x, y, area_w(), area_h())) continue;
                if (first < 0) first = x;
                last = x;
            }
            if (first < 0) break;
            std::fprintf(layout, "handle-reach %d %d %d\n", y, first, last);
        }
    }
    // The question: each choice of the keys, the pointer on each button and on the thin X, each button held; over the
    // dimmed game (the dim saved once, the card's window over it for each look).
    struct Ask {
        int choice, hover, pressed;
        const char* name;
    };
    QuestionPaint question;
    bool dim_saved = false;
    for (const Ask& a : {Ask{kKeep, kNone, kNone, "ask-keep"}, Ask{kQuit, kNone, kNone, "ask-quit"}, Ask{kKeep, kKeep, kNone, "ask-hover-keep"},
                         Ask{kKeep, kQuit, kNone, "ask-hover-quit"}, Ask{kKeep, kClose, kNone, "ask-hover-close"},
                         Ask{kKeep, kKeep, kKeep, "ask-pressed-keep"}, Ask{kKeep, kQuit, kQuit, "ask-pressed-quit"}}) {
        Order o;
        o.view = base;
        o.shots = shots;
        o.choice = a.choice;
        o.hover = a.hover;
        o.pressed = a.pressed;
        o.key = std::string("probe ") + a.name;
        g_test_texts = &g_test_words;
        Painted got = paint_question(o, question);
        g_test_texts = nullptr;
        if (!dim_saved && question.dim) {
            save_png(*question.dim, prefix + L"ask-dim.png");
            dim_saved = true;
            if (layout) std::fprintf(layout, "glass ask %d\n", got.glass ? 1 : 0);
        }
        // The card's window cut out of the whole picture: the rest is the dim.
        const AskScale cap;
        const AskLayout l = ask_layout();
        const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
        Canvas part(win.right - win.left, win.bottom - win.top);
        if (part.bits && got.picture && got.picture->bits) {
            for (int y = 0; y < part.h; ++y) {
                std::memcpy(static_cast<std::uint8_t*>(part.bits) + static_cast<std::size_t>(y) * static_cast<std::size_t>(part.w) * 4,
                            static_cast<std::uint8_t*>(got.picture->bits) +
                                (static_cast<std::size_t>(win.top + y) * static_cast<std::size_t>(got.picture->w) + static_cast<std::size_t>(win.left)) * 4,
                            static_cast<std::size_t>(part.w) * 4);
            }
            save_png(part, prefix + wide(a.name) + L".png");
            if (layout) std::fprintf(layout, "%s %ld %ld %d %d\n", a.name, win.left, win.top, part.w, part.h);
            words_lines(layout, a.name, static_cast<int>(win.left), static_cast<int>(win.top));
        }
    }
    {
        // The question made afresh over a new read: the whole frame's dim and the card's glass, then its look.
        LARGE_INTEGER f{}, a{}, b{};
        QueryPerformanceFrequency(&f);
        QuestionPaint fresh;
        Order o;
        o.view = base;
        o.shots = shots;
        o.key = "probe ask-time";
        QueryPerformanceCounter(&a);
        paint_question(o, fresh);
        QueryPerformanceCounter(&b);
        if (layout) std::fprintf(layout, "time ask %.3f\n", static_cast<double>(b.QuadPart - a.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart));
        // A new look over the same dim (the pointer onto another button).
        o.hover = kQuit;
        o.key = "probe ask-time-hover";
        QueryPerformanceCounter(&a);
        paint_question(o, fresh);
        QueryPerformanceCounter(&b);
        if (layout) std::fprintf(layout, "time ask-hover %.3f\n", static_cast<double>(b.QuadPart - a.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart));
    }
    {
        // Where the card, its buttons and its X are, for the checks' clicks and the overlaps.
        const AskScale cap;
        const AskLayout l = ask_layout();
        if (layout) {
            std::fprintf(layout, "card %.0f %.0f %.0f %.0f\n", l.card.X, l.card.Y, l.card.Width, l.card.Height);
            std::fprintf(layout, "keep %.0f %.0f %.0f %.0f\nquit %.0f %.0f %.0f %.0f\nclose %.0f %.0f %.0f %.0f\n", l.keep.X, l.keep.Y, l.keep.Width,
                         l.keep.Height, l.quit.X, l.quit.Y, l.quit.Width, l.quit.Height, l.close.X, l.close.Y, l.close.Width, l.close.Height);
            std::fprintf(layout, "ask-title %.0f %.0f %.0f %.0f\nask-text %.0f %.0f %.0f %.0f\n", l.title.X, l.title.Y, l.title.Width, l.title.Height, l.text.X,
                         l.text.Y, l.text.Width, l.text.Height);
        }
    }
    if (layout) {
        for (int which : {kMinChip, kScreenChip, kQuitChip}) {
            const RectF r = chip_rect(which, area_w());
            std::fprintf(layout, "%s %.0f %.0f %.0f %.0f\n", which == kQuitChip ? "chip-quit" : which == kScreenChip ? "chip-screen" : "chip-min", r.X, r.Y,
                         r.Width, r.Height);
        }
        std::fclose(layout);
    }
    g_test_quiet = false;
    g_test_no_words = false;
}

void test_motion(const std::wstring& prefix, const std::wstring& frame_png) {
    g_test_quiet = true;
    g_test_no_words = false;
    if (!test_frame(frame_png)) return;
    View base;
    base.w = g_test_frame_w;
    base.h = g_test_frame_h;
    base.dpi = window_dpi();
    const auto shots = test_read();
    const Drawing drawing(base);
    // The pictures, each made once as the painter makes it: the bar, the handle at rest and lit, the notice and a
    // counter at the top left where they stand without the bar.
    Order o;
    o.view = base;
    o.shots = shots;
    o.key = "probe motion bar";
    Paint bar_paint, handle_paint, lit_paint, notice_paint, counter_paint;
    const Painted bar = paint_bar(o, bar_paint);
    o.key = "probe motion handle";
    o.lit = false;
    const Painted handle = paint_handle(o, handle_paint);
    o.key = "probe motion handle lit";
    o.lit = true;
    const Painted lit = paint_handle(o, lit_paint);
    o.key = "probe motion notice";
    o.text = g_korean ? "이 플레이를 방송하고 있어요\nMy Server 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요" : "Broadcasting your play\nWatch it now or later under LIVE on My Server";
    o.live = true;
    o.corner = 1;
    const Painted notice = paint_notice(o, notice_paint);
    o.key = "probe motion counter";
    o.fps = 240;
    o.ms = 4.2f;
    const Painted counter = paint_counter(o, counter_paint);
    if (!bar.picture || !handle.picture || !lit.picture || !notice.picture || !counter.picture) return;
    FILE* numbers = _wfopen((prefix + L"motion.txt").c_str(), L"w");
    if (numbers) {
        // What every moment's numbers are read against: the area, the overlay's scale, the bar's rows, the handle's rail,
        // the ways' times.
        std::fprintf(numbers, "area %d %d\nscale %.4f\nbar-rows %d\nhandle-lip %d\ndown-ms %d\nup-ms %d\n", area_w(), area_h(), static_cast<double>(scale()),
                     bar.rows, handle.rows, kBarDownMs, kBarUpMs);
    }
    // What is saved of each: the game's top, twice the bar's own height and its shadow's room.
    const int kept = std::min(area_h(), bar.rows * 2 + px(kRoomBottom));
    for (const bool down : {true, false}) {
        // The whole way, from rest at one end to the other, on a clock that starts at 0.
        Slide way;
        way.rest(down ? 0.0f : 1.0f);
        way.aim(down ? 1.0f : 0.0f, 0, true);
        const std::int64_t whole = way.lasts;
        for (const int percent : {0, 25, 50, 75, 100}) {
            const float place = way.at(whole * percent / 100);
            const int rows = bar_rows(place, bar.rows);
            const float opacity = handle_opacity(place);
            const Hang hang = handle_hang(rows, handle.rows);
            if (numbers) {
                std::fprintf(numbers, "%s %d place %.4f rows %d handle-down %d handle-cut %d handle-opacity %.3f pieces-down %d\n", down ? "down" : "up", percent,
                             static_cast<double>(place), rows, hang.down, hang.cut, static_cast<double>(opacity), rows);
            }
            // Two sets: the handle and the bar alone (brought by the pointer on the handle: lit as the bar sets out, at
            // rest as the bar goes up), and the notice and the counter moving with the bar (no handle beside a notice).
            for (const bool busy : {false, true}) {
                std::vector<std::uint8_t> screen = g_test_frame;
                if (busy) {
                    // Lower by the rows in sight: both were placed for no bar.
                    lay_over(screen, g_test_frame_w, g_test_frame_h, *counter.picture, counter.x, counter.y + rows, 0, kCounterAlpha);
                    lay_over(screen, g_test_frame_w, g_test_frame_h, *notice.picture, notice.x, notice.y + rows, 0, 255);
                }
                // The bar over them, its foot at the edge first.
                if (rows > 0) lay_over(screen, g_test_frame_w, g_test_frame_h, *bar.picture, bar.x, bar.y, bar.rows - rows, 255);
                // The handle over the bar's shadow, on its foot (its window is above the bar's).
                if (!busy && opacity > 0.0f) {
                    const Painted& tab = down ? lit : handle;
                    lay_over(screen, g_test_frame_w, g_test_frame_h, *tab.picture, tab.x, tab.y + hang.down, hang.cut, static_cast<BYTE>(std::lround(255.0f * opacity)));
                }
                wchar_t name[64];
                std::swprintf(name, 64, L"motion-%ls-%ls-%03d.png", busy ? L"busy" : L"plain", down ? L"down" : L"up", percent);
                save_rows(screen, g_test_frame_w, kept, prefix + name);
            }
        }
    }
    if (numbers) std::fclose(numbers);
    g_test_quiet = false;
}

void test_set_dpi(float scale) { g_test_dpi = scale; }

#endif

}  // namespace player::overlay
