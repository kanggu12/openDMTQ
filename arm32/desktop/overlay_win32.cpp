// What the player for Windows draws over the game itself (window_win32.cpp places and feeds it), in the game's own look:
// the dark header of its dialogs (#1C1C1C) with the lime glow along its bottom edge, its grey body, its square OFF chips
// and its green buttons, nearly square corners, white bold text. Red only for a live broadcast. Each is a layered window
// of its own above the game's window, drawn with GDI+ into a premultiplied 32-bit bitmap and shown with
// UpdateLayeredWindow, so its edges are smooth and its fades cost the game nothing.
//
// - The bar: a PC has no phone's buttons around the game, so a bar across the top of the game's area, as the game's
//   dialog header, shows when the pointer touches the very top edge with its button up, or when a finger is drawn down
//   from the top edge. "OpenDMTQ" on its left; on its right two chips, full screen (or back to a window) and an X that
//   quits after asking. It stays while the pointer is on it and fades soon after it leaves, so it never sits on the
//   game's own controls at the top while they are used. No key opens it.
// - The question before quitting: the bar's X and the window's own close ask it, as the game's dialogs ask (the game
//   dimmed behind, a header with the title and a thin X, the glow line, the grey body, a green Keep playing and a grey
//   Quit the game), and the game holds still meanwhile; a click by mistake mid-song loses nothing. Alt+F4 does nothing.
// - The notice: the server's two-line notice about a broadcast (a title, then where to watch), as a small card of the
//   same header's look that slides down at the top of the game, stays for a few seconds and fades. A red LIVE mark
//   while broadcasting, a grey one when the broadcast has ended.
// - The cursor: a dart in the logo's chrome and lime, all lime while the mouse's finger is down on the game.
// - The frame counter: when the PC's settings ask for it, a small chip of the header's look in the corner the player
//   picks, 8 pixels in at 720 lines: the frames a second as the game's lime numbers with "FPS" beside them, and the mean
//   frame time under them, over the last half second, drawn twice a second from the count of frames shown that the
//   player keeps anyway (frames.cpp). It lets clicks through, and stays under the question's dim while that is up.
#include "overlay_win32.h"

// GDI+ and the picture it draws into, which the error box before the game draws with too (error_box_win32.cpp, where
// error_box and its test_save_error_box are).
#include "canvas_win32.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cwchar>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace player::overlay {

namespace {

using namespace Gdiplus;

HWND g_frame = nullptr, g_game = nullptr;
Hooks g_hooks{};
bool g_korean = false;
ULONG_PTR g_gdiplus = 0;

// The look, taken from the game's own screens at 1280x720 (its "Select Game Screen Type!" dialog, its OFF chips).
// The header of its dialogs, opaque: as the bar it covers the game's own top controls, which would otherwise show through.
const Color kHeader(255, 28, 28, 28);
// The body of its dialogs, under the header.
const Color kBody(255, 48, 50, 55);
// The lime of the glow under a dialog's header, at its brightest.
const Color kGlow(255, 90, 200, 20);
// A chip at rest, as the game's OFF chips: the fill and its one-pixel edge.
const Color kChip(255, 52, 54, 58);
const Color kChipEdge(255, 78, 80, 86);
// The game's green button (its OK): light at the top, deep at the bottom, a darker edge; lighter under the pointer.
const Color kGreenTop(255, 69, 163, 8), kGreenBottom(255, 36, 97, 0), kGreenEdge(255, 22, 64, 0);
const Color kGreenTopHover(255, 88, 188, 22), kGreenBottomHover(255, 48, 120, 6);
// Held down: deeper, darker at the top than at the bottom, as a button pressed in.
const Color kGreenPressedTop(255, 28, 78, 0), kGreenPressedBottom(255, 44, 116, 4);
// The grey button beside it, for the choice that is not the game's way on; lighter under the pointer.
const Color kGreyTop(255, 85, 88, 94), kGreyBottom(255, 58, 60, 65), kGreyEdge(255, 34, 36, 40);
const Color kGreyTopHover(255, 104, 108, 115), kGreyBottomHover(255, 72, 75, 81);
const Color kGreyPressedTop(255, 46, 48, 52), kGreyPressedBottom(255, 66, 69, 74);
// The ring of the button the keys chose: the logo's lime, plain to see on the grey body.
const Color kChosen(255, 140, 242, 61);
// The dialogs' white text, and the quiet grey of a line that only explains.
const Color kText(255, 255, 255, 255);
const Color kQuiet(255, 178, 182, 190);
// The light line along the top of the game's dialogs, and the dark one around them.
const Color kTopLight(34, 255, 255, 255);
const Color kOutline(170, 8, 8, 8);
// The broadcast's mark: red while live (white bold text on it at 4.8:1), grey once it ended.
const Color kLive(255, 209, 58, 64);
const Color kEnded(255, 108, 116, 128);

#ifdef OVERLAY_TEST_HOOKS
// The probe's stand-in for Windows' scale (0: Windows' own), so that 150 % can be drawn on a PC at 100 %.
float g_test_dpi = 0;
// The probe's places as with the bar up (top_room).
bool g_test_bar_up = false;
#endif

// The scale of the game's display (Windows' own, 1 at 96 dpi).
float dpi_scale() {
#ifdef OVERLAY_TEST_HOOKS
    // The probe's scale, when it set one.
    if (g_test_dpi > 0) return g_test_dpi;
#endif
    using DpiOf = UINT(WINAPI*)(HWND);
    // Windows 10 1607 has the call; an older one is taken as 96 dpi.
    static auto dpi_of = reinterpret_cast<DpiOf>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
    return (dpi_of && g_frame ? static_cast<float>(dpi_of(g_frame)) : 96.0f) / 96.0f;
}

// The game's area on the screen.
RECT area() {
    RECT r{};
    // The game's own window, or the frame before it is made.
    GetWindowRect(g_game ? g_game : g_frame, &r);
    return r;
}

// The overlay's scale: the game's, which lays itself out for 720 lines and grows with its area (1.5 at 1080 lines, 3 at
// 4K), or Windows' own when that is larger (a small window on a display at 200 %), so that the bar, the question and the
// notice keep their size beside the game's own dialogs and buttons.
// A cap on the scale while one piece is laid out and drawn (0: none): the question's card, which keeps within the
// game's area (AskScale below).
float g_scale_cap = 0;

float scale() {
    const RECT a = area();
    const float s = std::max(dpi_scale(), static_cast<float>(a.bottom - a.top) / 720.0f);
    return g_scale_cap > 0 ? std::min(s, g_scale_cap) : s;
}

// The question's card at most three quarters of the game's area wide (600 at 720 lines) and nine tenths of it high
// (218 at 720 lines), everything in it scaled with it: a small window on a display at 150 % or 200 % gets a card in
// proportion to the game instead of one across its whole width. Held while the card is laid out or drawn.
struct AskScale {
    float before;
    AskScale() : before(g_scale_cap) {
        const RECT a = area();
        const float w = static_cast<float>(a.right - a.left), h = static_cast<float>(a.bottom - a.top);
        g_scale_cap = std::min(0.75f * w / 600.0f, 0.9f * h / 218.0f);
    }
    ~AskScale() { g_scale_cap = before; }
    AskScale(const AskScale&) = delete;
    AskScale& operator=(const AskScale&) = delete;
};
// A length of the game's at 720 lines as pixels at the overlay's scale, whole (edges on whole pixels stay sharp). Every
// size of the overlay goes through here.
int px(float at720) { return static_cast<int>(std::lround(at720 * scale())); }

// A rounded rectangle as a path.
void rounded(GraphicsPath& path, RectF r, float radius) {
    // The corners' arcs no larger than the rectangle allows.
    const float d = std::min(radius * 2, std::min(r.Width, r.Height));
    path.AddArc(r.X, r.Y, d, d, 180, 90);
    path.AddArc(r.X + r.Width - d, r.Y, d, d, 270, 90);
    path.AddArc(r.X + r.Width - d, r.Y + r.Height - d, d, d, 0, 90);
    path.AddArc(r.X, r.Y + r.Height - d, d, d, 90, 90);
    path.CloseFigure();
}

// A soft shadow under a card, a few rings each wider and fainter, a little lower than the card: it lifts the card off
// the game as the game's own dialogs sit on it.
void shadow(Graphics& g, RectF r, float radius) {
    for (int i = 3; i >= 1; --i) {
        GraphicsPath ring;
        const float grow = static_cast<float>(px(2.0f * i));
        rounded(ring, RectF(r.X - grow, r.Y - grow + px(2), r.Width + grow * 2, r.Height + grow * 2), radius + grow);
        SolidBrush b(Color(static_cast<BYTE>(16 * (4 - i)), 0, 0, 0));
        g.FillPath(&b, &ring);
    }
}

// The game's lime glow along the line from x to x + w whose top is at y: a line of two pixels, brightest in the middle
// and fading to nothing at both ends, with a faint haze above it as the game's dialog header has.
void glow(Graphics& g, float x, float y, float w) {
    // How strong the glow is along the line: a bell, whole in the middle, nothing at the ends (sampled from the game's
    // dialog, where it is gone a fifth of the width either side of the middle; a little wider here, for a long bar).
    const REAL at[] = {0.0f, 0.12f, 0.28f, 0.5f, 0.72f, 0.88f, 1.0f};
    const float bell[] = {0.0f, 0.05f, 0.4f, 1.0f, 0.4f, 0.05f, 0.0f};
    // One band of the glow, `height` pixels from `top`, at `strength` of the whole.
    auto band = [&](float top, float height, float strength) {
        Color colours[7];
        for (int i = 0; i < 7; ++i) colours[i] = Color(static_cast<BYTE>(255 * strength * bell[i]), kGlow.GetR(), kGlow.GetG(), kGlow.GetB());
        // Across the line's whole width, so that the bell's ends fall on its ends.
        LinearGradientBrush brush(PointF(x, 0), PointF(x + w, 0), colours[0], colours[6]);
        brush.SetInterpolationColors(colours, at, 7);
        g.FillRectangle(&brush, x, top, w, height);
    };
    // The haze: a row at a time above the line, each fainter than the one under it (as sampled: a third, a fifth, a
    // tenth of the line, then almost nothing).
    const float haze[] = {0.34f, 0.2f, 0.1f, 0.05f};
    const float row = static_cast<float>(std::max(1, px(1)));
    for (int i = 0; i < 4; ++i) band(y - row * static_cast<float>(i + 1), row, haze[i]);
    // The line itself.
    band(y, static_cast<float>(std::max(2, px(2))), 1.0f);
}

// A button of the game's: a vertical gradient from `top` to `bottom` in a rectangle with nearly square corners, a darker
// edge one pixel inside it, and a faint light line along its top as the game's green OK has.
void button(Graphics& g, RectF r, float radius, const Color& top, const Color& bottom, const Color& edge) {
    GraphicsPath path;
    rounded(path, r, radius);
    // A pixel beyond both ends, so that the gradient's own ends do not wrap over the first and last rows.
    LinearGradientBrush fill(PointF(0, r.Y - 1), PointF(0, r.Y + r.Height + 1), top, bottom);
    g.FillPath(&fill, &path);
    // The edge on the button's outermost pixels: half a pixel in, so that the pen's width falls inside it.
    GraphicsPath rim;
    rounded(rim, RectF(r.X + 0.5f, r.Y + 0.5f, r.Width - 1, r.Height - 1), radius);
    Pen pen(edge, 1.0f);
    g.DrawPath(&pen, &rim);
    // The light along its top, inside the edge and clear of the corners.
    Pen light(Color(46, 255, 255, 255), 1.0f);
    g.DrawLine(&light, r.X + radius, r.Y + 1.5f, r.X + r.Width - radius, r.Y + 1.5f);
}

// Text centred in a box, on one line, in the face for the language.
void centred(Graphics& g, const wchar_t* text, float size, bool bold, const Color& colour, RectF box) {
    const auto family = face(g_korean);
    Font font(family.get(), static_cast<REAL>(size), bold ? FontStyleBold : FontStyleRegular, UnitPixel);
    StringFormat format;
    format.SetAlignment(StringAlignmentCenter);
    format.SetLineAlignment(StringAlignmentCenter);
    // One line: a narrow box cuts it with an ellipsis rather than breaking it under itself.
    format.SetFormatFlags(StringFormatFlagsNoWrap);
    format.SetTrimming(StringTrimmingEllipsisCharacter);
    SolidBrush brush(colour);
    g.DrawString(text, -1, &font, box, &format, &brush);
}

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

// ---- the notice

HWND g_notice = nullptr;
std::unique_ptr<Canvas> g_notice_canvas;
UINT64 g_notice_shown = 0;  // GetTickCount64 when it came
constexpr UINT_PTR kNoticeTimer = 1;
// Sliding in, staying, fading out.
constexpr UINT64 kSlideMs = 220, kStayMs = 6000, kFadeMs = 350;

// The room the bar takes at the top of the game's area while it is up (0 while it is not): what sits at the top moves
// under it rather than being covered (bar_frame and hide_bar move them).
int top_room();

// The notice's place once it has slid in: centred at the top of the game's area, a little down from its edge, and
// under the bar while that is up.
POINT notice_place(const Canvas& c) {
    const RECT a = area();
    return POINT{(a.left + a.right - c.w) / 2, a.top + px(14) + top_room()};
}

void notice_frame() {
    if (!g_notice_canvas) return;
    const UINT64 t = GetTickCount64() - g_notice_shown;
    float alpha = 1, drop = 0;
    if (t < kSlideMs) {
        // In: down from a little above, fading in, easing out.
        const float k = static_cast<float>(t) / kSlideMs;
        const float ease = 1 - (1 - k) * (1 - k);
        alpha = ease;
        drop = (1 - ease) * px(10);
    } else if (t > kSlideMs + kStayMs) {
        alpha = 1 - std::min(1.0f, static_cast<float>(t - kSlideMs - kStayMs) / kFadeMs);
    }
    // Gone only once the fade out is over: the first frame of the slide in is transparent as well.
    if (alpha <= 0 && t > kSlideMs) {
        KillTimer(g_notice, kNoticeTimer);
        ShowWindow(g_notice, SW_HIDE);
        g_notice_canvas.reset();
        return;
    }
    const POINT at = notice_place(*g_notice_canvas);
    g_notice_canvas->show(g_notice, at.x, at.y - static_cast<int>(drop), static_cast<BYTE>(alpha * 255));
    // The next step: every 15 ms while it slides or fades; while it stays, once, when the fade begins.
    const bool staying = t >= kSlideMs && t < kSlideMs + kStayMs;
    SetTimer(g_notice, kNoticeTimer, staying ? static_cast<UINT>(kSlideMs + kStayMs - t) : 15, nullptr);
}

LRESULT CALLBACK notice_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_TIMER && w == kNoticeTimer) {
        notice_frame();
        return 0;
    }
    // Clicks go through it to the game: it only tells.
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(h, msg, w, l);
}

// ---- the frame counter

}  // namespace

// The frames a second and the mean frame time from two looks at the count: the frames between the two looks' last
// frames over the time between those frames, which are the display's own moments (a look's own time would add the
// timer's lateness, and a frame either side of a look would make a steady 60 read 58 or 62). No frame since the last
// look (the game held still): 0 frames a second, no time. Before a first look (`before`'s time 0): `fps` and `ms` stay.
void rate(const FrameCount& before, const FrameCount& now, int& fps, float& ms) {
    if (!before.ns) return;
    const unsigned long long frames = now.count - before.count;
    const long long span = now.ns - before.ns;
    if (!frames || span <= 0) {
        fps = 0;
        ms = 0;
        return;
    }
    const double mean = static_cast<double>(span) / 1e6 / static_cast<double>(frames);
    // Three digits at most: the counter's room.
    fps = std::min(999, static_cast<int>(std::lround(1000.0 / mean)));
    ms = static_cast<float>(mean);
}

namespace {

HWND g_fps = nullptr;
// Its corner (Settings::ShowFps's order, 0 none) and the count of frames shown it reads, with the last one's time.
int g_fps_corner = 0;
FrameCount (*g_fps_frames)() = nullptr;
constexpr UINT_PTR kFpsTimer = 3;
// Twice a second.
constexpr UINT kFpsMs = 500;
// The count and its last frame's time at the last look (none yet: count 0 and time 0), and what it showed (-1: nothing
// yet).
FrameCount g_fps_last{};
int g_fps_shown = -1;
float g_fps_shown_ms = 0;
std::unique_ptr<Canvas> g_fps_canvas;
// The scale its picture was drawn at: a new one (a resize, another display) draws it again.
float g_fps_canvas_scale = 0;
// The look: the header's dark at about 92 % (the time's quiet grey keeps 4.5:1 even over the game's white), its thin
// edge, the game's lime for the number.
const Color kCounter(235, 28, 28, 28);
const Color kCounterEdge(150, 90, 92, 98);

// The counter's picture showing `fps` frames a second and `ms` a frame (fps below 0: not known yet, dashes). Its size
// does not change with the numbers: room for three digits and "99.9 ms".
std::unique_ptr<Canvas> make_fps(int fps, float ms) {
    // Digits and Latin letters: the UI face of either language.
    const auto family = face(false);
    Font number_font(family.get(), static_cast<REAL>(px(20)), FontStyleBold, UnitPixel);
    Font unit_font(family.get(), static_cast<REAL>(px(11)), FontStyleBold, UnitPixel);
    Font time_font(family.get(), static_cast<REAL>(px(11)), FontStyleRegular, UnitPixel);
    const float pad = static_cast<float>(px(8)), gap = static_cast<float>(px(4));
    RectF number_box, unit_box, time_box;
    // The words set tight, without GDI+'s own room either side (a sixth of the size, more for the large number than for
    // the small time under it): their left edges line up at the chip's padding.
    std::unique_ptr<StringFormat> tight(StringFormat::GenericTypographic()->Clone());
    {
        // A one-pixel picture to measure the widest numbers on.
        Bitmap probe(1, 1, PixelFormat32bppPARGB);
        Graphics g(&probe);
        text_setup(g);
        g.MeasureString(L"888", -1, &number_font, PointF(0, 0), tight.get(), &number_box);
        g.MeasureString(L"FPS", -1, &unit_font, PointF(0, 0), tight.get(), &unit_box);
        g.MeasureString(L"88.8 ms", -1, &time_font, PointF(0, 0), tight.get(), &time_box);
    }
    // The number's line a little tighter than the face's own height: the time sits close under it.
    const float number_h = number_box.Height * 0.86f;
    const int w = static_cast<int>(std::ceil(pad * 2 + std::max(number_box.Width + gap + unit_box.Width, time_box.Width)));
    const int h = static_cast<int>(std::ceil(pad * 1.5f + number_h + time_box.Height));
    auto canvas = std::make_unique<Canvas>(w, h);
    auto bmp = canvas->surface();
    Graphics g(bmp.get());
    text_setup(g);
    // The chip on whole pixels, its edge half a pixel in.
    const RectF box(0.5f, 0.5f, static_cast<REAL>(w) - 1, static_cast<REAL>(h) - 1);
    GraphicsPath chip;
    rounded(chip, box, static_cast<float>(px(4)));
    SolidBrush fill(kCounter);
    g.FillPath(&fill, &chip);
    Pen edge(kCounterEdge, 1.0f);
    g.DrawPath(&edge, &chip);
    // The number, then "FPS" small on its baseline's side, then the time under them.
    const std::wstring number = fps < 0 ? L"--" : std::to_wstring(fps);
    wchar_t time[32];
    // No frame in the half second (the game held still): no time between frames either.
    if (fps <= 0) std::swprintf(time, 32, L"-- ms");
    else std::swprintf(time, 32, L"%.1f ms", static_cast<double>(ms));
    SolidBrush lime(kChosen), quiet(kQuiet);
    RectF drawn;
    g.MeasureString(number.c_str(), -1, &number_font, PointF(0, 0), tight.get(), &drawn);
    const float top = pad * 0.6f;
    g.DrawString(number.c_str(), -1, &number_font, PointF(pad, top), tight.get(), &lime);
    // "FPS" at the number's foot: the bottom of its box less the face's own room below the digits.
    const float foot = top + number_box.Height * 0.78f;
    g.DrawString(L"FPS", -1, &unit_font, PointF(pad + drawn.Width + gap, foot - unit_box.Height * 0.78f), tight.get(), &quiet);
    g.DrawString(time, -1, &time_font, PointF(pad, top + number_h), tight.get(), &quiet);
    return canvas;
}

// The right edge of the game's pause button in a song, at 720 lines: the button spans 13 to 72 from the left (measured
// on the game's frames), at the game's own scale (its height over 720), whatever Windows' scale.
constexpr float kPauseRight = 73;

// The counter's place: its corner of the game's area, 8 pixels in at 720 lines; top left, 8 pixels right of the
// game's pause button, so that it covers nothing a song uses; in a top corner, under the bar while that is up.
POINT fps_place(const Canvas& c) {
    const RECT a = area();
    const int in = px(8);
    const bool right = g_fps_corner == 2 || g_fps_corner == 4, bottom = g_fps_corner == 3 || g_fps_corner == 4;
    const float game = static_cast<float>(a.bottom - a.top) / 720.0f;
    const int left = g_fps_corner == 1 ? static_cast<int>(std::lround(kPauseRight * game)) + in : in;
    return POINT{right ? a.right - in - c.w : a.left + left, bottom ? a.bottom - in - c.h : a.top + in + top_room()};
}

// The counter where its corner is now, drawn again only when its scale changed: a move of the window counts nothing.
void fps_place_now() {
    if (!g_fps || !g_fps_corner) return;
    if (!g_fps_canvas || g_fps_canvas_scale != scale()) {
        g_fps_canvas = make_fps(g_fps_shown, g_fps_shown_ms);
        g_fps_canvas_scale = scale();
    }
    const POINT at = fps_place(*g_fps_canvas);
    g_fps_canvas->show(g_fps, at.x, at.y, 255);
}

// A look at the count, twice a second: the frames since the last look over the time between their own last frames,
// drawn again when what it shows changed.
void fps_frame() {
    if (!g_fps || !g_fps_frames) return;
    const FrameCount now = g_fps_frames();
    int fps = g_fps_shown;
    float ms = g_fps_shown_ms;
    rate(g_fps_last, now, fps, ms);
    // Held still (no frame since the last look): the next look starts afresh from its own count, so that the time the
    // game stood still is not taken for one long frame once it goes on.
    g_fps_last = fps == 0 ? FrameCount{} : now;
    if (!g_fps_canvas || fps != g_fps_shown || std::fabs(ms - g_fps_shown_ms) >= 0.05f) {
        g_fps_shown = fps;
        g_fps_shown_ms = ms;
        // Drawn afresh by fps_place_now.
        g_fps_canvas.reset();
    }
    fps_place_now();
}

LRESULT CALLBACK fps_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_TIMER && w == kFpsTimer) {
        fps_frame();
        return 0;
    }
    // Clicks go through it to the game: it only tells.
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(h, msg, w, l);
}

// ---- the bar

HWND g_bar = nullptr;
// What is under the pointer on the bar: nothing, the X (at the right end) or the full screen chip (left of it).
constexpr int kNone = -1, kQuitChip = 0, kScreenChip = 1;
int g_bar_hover = kNone;
// When the bar last had the pointer on it (or came), and how long it stays whole after that before it fades.
UINT64 g_bar_since = 0, g_bar_stay = 0;
// The bar's one timer: a look at the pointer while it is whole, each step of its fade after.
constexpr UINT_PTR kBarTimer = 2;
// Whole for 600 ms after the pointer leaves it, then fading over 300 ms a step at a time; shown by a finger, whole for
// 4 s (a finger has no pointer that stays on it). While whole it looks for the pointer ten times a second.
constexpr UINT64 kBarStayMs = 600, kBarFadeMs = 300, kBarTouchStayMs = 4000, kBarStepMs = 30, kBarLookMs = 100;
// Shown by a finger: the pointer Windows parks where the finger was is no mouse on the bar, until the mouse moves.
bool g_bar_by_touch = false;
// The chip the mouse's button (or a finger) went down on: it acts only when let go on the same chip, and looks pressed
// while it is held there.
int g_bar_pressed = kNone;
// The pointer at the top edge waits this long before the bar shows, and shows it only if it is still there: a pointer
// on its way to the window's title bar above, or flicked past the edge mid-song, shows nothing.
constexpr UINT_PTR kBarEdgeTimer = 4;
constexpr UINT kBarEdgeMs = 150;
// Whether the mouse's button was down at its last move over the game (it plays then: no bar).
bool g_pointer_down = false;
// The bar's picture, kept while it looks the same (its width, the overlay's scale, the chip under the pointer, full
// screen or not): its fade and its moves with the game show the same picture at another opacity or place.
std::unique_ptr<Canvas> g_bar_canvas;
int g_bar_canvas_w = 0, g_bar_canvas_hover = kNone, g_bar_canvas_pressed = kNone;
float g_bar_canvas_scale = 0;
bool g_bar_canvas_full = false;
// What was shown last (the picture's version, the opacity, the place): the same again is not sent to Windows again.
int g_bar_version = 0, g_bar_shown_version = -1;
BYTE g_bar_shown_alpha = 0;
POINT g_bar_shown_at{};

// The bar's height, the chips' size, the gap between them and their room from the bar's right end, at this scale. 74
// at 720 lines: the game's own X at the top right of its song and music screens reaches row 70 (its soft edge, measured
// on the game's frames), and the bar covers it whole with 4 to spare, no tip of it showing under the glow.
int bar_height() { return px(74); }
int chip_size() { return px(36); }
int chip_gap() { return px(10); }
int chip_margin() { return px(14); }

int top_room() {
#ifdef OVERLAY_TEST_HOOKS
    // The probe's places with the bar up, its windows being hidden.
    if (g_test_bar_up) return bar_height();
#endif
    return g_bar && IsWindowVisible(g_bar) ? bar_height() : 0;
}

// A chip's square on a bar `w` pixels wide: the X at the right end, the full screen chip left of it; both centred in
// the bar's height.
RectF chip_rect(int which, int w) {
    const float size = static_cast<float>(chip_size());
    const float x = static_cast<float>(w - chip_margin() - chip_size() - which * (chip_size() + chip_gap()));
    return RectF(x, static_cast<float>((bar_height() - chip_size()) / 2), size, size);
}

// The chip under a point of the bar's window, or kNone.
int chip_at(int x, int y) {
    const RECT a = area();
    for (int which : {kQuitChip, kScreenChip}) {
        if (chip_rect(which, a.right - a.left).Contains(static_cast<REAL>(x), static_cast<REAL>(y))) return which;
    }
    return kNone;
}

// Whether the frame is in full screen, as the window says.
bool full_screen() { return g_hooks.fullscreen && g_hooks.fullscreen(); }

// The full screen chip's icon in a chip centred at (cx, cy): four corner brackets, their corners out (to full screen)
// or in (back to a window, when `full`).
void screen_icon(Graphics& g, Pen& line, float cx, float cy, bool full) {
    // The brackets' reach from the centre and the length of each arm.
    const float outer = static_cast<float>(px(8)), inner = static_cast<float>(px(3)), arm = static_cast<float>(px(4.5f));
    for (int sx : {-1, 1}) {
        for (int sy : {-1, 1}) {
            // Out: the corner at the outer point, the arms going back in; in: the corner near the centre, the arms
            // going out, as the corners of a smaller square pushed in.
            const float corner = full ? inner : outer;
            const float back = full ? arm : -arm;
            const PointF bracket[] = {PointF(cx + sx * corner, cy + sy * (corner + back)), PointF(cx + sx * corner, cy + sy * corner),
                                      PointF(cx + sx * (corner + back), cy + sy * corner)};
            g.DrawLines(&line, bracket, 3);
        }
    }
}

// An X centred at (cx, cy), `half` from its centre to each end.
void cross(Graphics& g, Pen& line, float cx, float cy, float half) {
    g.DrawLine(&line, cx - half, cy - half, cx + half, cy + half);
    g.DrawLine(&line, cx - half, cy + half, cx + half, cy - half);
}

// The bar's picture as it looks now, drawn only when its look changed.
Canvas& bar_canvas() {
    const RECT a = area();
    const int w = std::max(1, static_cast<int>(a.right - a.left));
    const float now_scale = scale();
    const bool full = full_screen();
    if (g_bar_canvas && g_bar_canvas_w == w && g_bar_canvas_hover == g_bar_hover && g_bar_canvas_pressed == g_bar_pressed &&
        g_bar_canvas_scale == now_scale && g_bar_canvas_full == full) {
        return *g_bar_canvas;
    }
    const int h = bar_height();
    g_bar_canvas = std::make_unique<Canvas>(w, h);
    g_bar_canvas_w = w;
    g_bar_canvas_hover = g_bar_hover;
    g_bar_canvas_pressed = g_bar_pressed;
    g_bar_canvas_scale = now_scale;
    g_bar_canvas_full = full;
    ++g_bar_version;
    {
        auto bmp = g_bar_canvas->surface();
        Graphics g(bmp.get());
        text_setup(g);
        // The game's dialog header, across the game's whole width.
        SolidBrush header(kHeader);
        g.FillRectangle(&header, 0, 0, w, h);
        // The glow along its bottom edge, its two pixels the bar's last.
        const float line = static_cast<float>(std::max(2, px(2)));
        glow(g, 0, static_cast<float>(h) - line, static_cast<float>(w));
        // The name on the left, in the game's white bold, over the bar's height above the glow.
        const auto family = face(g_korean);
        Font name(family.get(), static_cast<REAL>(px(17)), FontStyleBold, UnitPixel);
        StringFormat middle;
        middle.SetLineAlignment(StringAlignmentCenter);
        middle.SetFormatFlags(StringFormatFlagsNoWrap);
        SolidBrush white(kText);
        g.DrawString(L"OpenDMTQ", -1, &name, RectF(static_cast<REAL>(px(18)), 0, static_cast<REAL>(px(240)), static_cast<REAL>(h) - line), &middle, &white);
        // The two chips: at rest as the game's OFF chips; under the pointer, the full screen chip as the game's green
        // button and the X as its grey one; held down, that button pressed in (deeper, its light at the bottom); a
        // white glyph on all.
        const float radius = static_cast<float>(px(5));
        for (int which : {kQuitChip, kScreenChip}) {
            const RectF r = chip_rect(which, w);
            // The X lights grey, not the game's green, which says go on; the full screen chip lights green.
            const bool quit = which == kQuitChip;
            if (which == g_bar_hover && which == g_bar_pressed) {
                if (quit) button(g, r, radius, kGreyPressedTop, kGreyPressedBottom, kGreyEdge);
                else button(g, r, radius, kGreenPressedTop, kGreenPressedBottom, kGreenEdge);
            } else if (which == g_bar_hover) {
                // White on its lightest grey (104, 108, 115) is 5.3:1.
                if (quit) button(g, r, radius, kGreyTopHover, kGreyBottomHover, kGreyEdge);
                else button(g, r, radius, kGreenTop, kGreenBottom, kGreenEdge);
            } else {
                GraphicsPath path;
                rounded(path, RectF(r.X + 0.5f, r.Y + 0.5f, r.Width - 1, r.Height - 1), radius);
                SolidBrush fill(kChip);
                g.FillPath(&fill, &path);
                Pen edge(kChipEdge, 1.0f);
                g.DrawPath(&edge, &path);
            }
            // The glyph's line: 2.6 pixels at 720 lines, square ends for the brackets' corners, round for the X.
            Pen line_pen(kText, 2.6f * scale());
            line_pen.SetLineJoin(LineJoinMiter);
            const float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2;
            if (which == kQuitChip) {
                line_pen.SetStartCap(LineCapRound);
                line_pen.SetEndCap(LineCapRound);
                cross(g, line_pen, cx, cy, static_cast<float>(px(6.5f)));
            } else {
                screen_icon(g, line_pen, cx, cy, full);
            }
        }
    }
    return *g_bar_canvas;
}

// The notice and a counter in a top corner, placed again for the bar's coming or going (under it, or back up).
void move_for_bar() {
    fps_place_now();
    if (g_notice_canvas) notice_frame();
}

// The bar gone: hidden, its timer stopped, nothing under the pointer or held on it.
void hide_bar() {
    if (!g_bar) return;
    const bool was = IsWindowVisible(g_bar) != FALSE;
    ShowWindow(g_bar, SW_HIDE);
    KillTimer(g_bar, kBarTimer);
    g_bar_hover = kNone;
    // A chip held as it goes is let go of without acting: forgotten before the capture goes, so that the bar's
    // WM_CAPTURECHANGED finds nothing held and does not draw the bar again.
    const bool held = g_bar_pressed != kNone;
    g_bar_pressed = kNone;
    if (held && GetCapture() == g_bar) ReleaseCapture();
    g_bar_shown_version = -1;
    if (was) move_for_bar();
}

// Whether the mouse's pointer is on the bar's strip at the top of the game's area (shown by a finger, it is not until
// the mouse moves).
bool pointer_on_bar() {
    if (g_bar_by_touch || !IsWindowVisible(g_bar)) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    return p.x >= a.left && p.x < a.right && p.y >= a.top && p.y < a.top + bar_height();
}

// The bar at the opacity its time gives it (whole while the pointer is on it and for g_bar_stay after, then fading),
// at the top of the game's area, or hidden once it faded or while the question is up; its one timer set for its next
// look.
void bar_frame() {
    if (!g_bar) return;
    const UINT64 now = GetTickCount64();
    if (pointer_on_bar()) {
        // On it: its time starts again, and it stays whole for kBarStayMs after the pointer leaves.
        g_bar_since = now;
        g_bar_stay = kBarStayMs;
    } else {
        // Off it, perhaps between two of its moves: no chip is under the pointer.
        g_bar_hover = kNone;
    }
    const UINT64 idle = now - g_bar_since;
    float alpha = 1;
    if (idle > g_bar_stay) alpha = 1 - std::min(1.0f, static_cast<float>(idle - g_bar_stay) / kBarFadeMs);
    if (alpha <= 0 || asking()) {
        hide_bar();
        return;
    }
    // The kept picture (drawn again only when its look changed), shown again only when it, its opacity or its place
    // changed: a look at the pointer that finds all as it was costs nothing.
    Canvas& c = bar_canvas();
    const RECT a = area();
    const auto byte = static_cast<BYTE>(alpha * 255);
    if (g_bar_shown_version != g_bar_version || g_bar_shown_alpha != byte || g_bar_shown_at.x != a.left || g_bar_shown_at.y != a.top) {
        c.show(g_bar, a.left, a.top, byte);
        g_bar_shown_version = g_bar_version;
        g_bar_shown_alpha = byte;
        g_bar_shown_at = POINT{a.left, a.top};
    }
    if (!IsWindowVisible(g_bar)) {
        ShowWindow(g_bar, SW_SHOWNOACTIVATE);
        // The notice and a counter at the top move under it.
        move_for_bar();
    }
    // Fading: the next step. Whole: the next look at the pointer, or the fade's start if that comes first.
    const UINT64 next = alpha < 1 ? kBarStepMs : std::min(kBarLookMs, g_bar_stay - idle + 1);
    SetTimer(g_bar, kBarTimer, static_cast<UINT>(std::max<UINT64>(1, next)), nullptr);
}

// Whether the mouse's pointer rests at the very top edge of the game's area now (within the bar's height, over the
// game's own window, its button up): the edge's wait is over and the bar shows.
bool pointer_at_edge() {
    if (asking() || g_pointer_down) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    if (p.x < a.left || p.x >= a.right || p.y < a.top || p.y >= a.top + bar_height()) return false;
    // Another window over the game there (another program's, the title bar of none): not the game's edge.
    return WindowFromPoint(p) == g_game;
}

// The bar shown whole, staying `stay` ms (more while the pointer is on it).
void reveal(UINT64 stay) {
    g_bar_since = GetTickCount64();
    g_bar_stay = stay;
    bar_frame();
}

LRESULT CALLBACK bar_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_TIMER:
        if (w == kBarTimer) bar_frame();
        if (w == kBarEdgeTimer) {
            KillTimer(h, kBarEdgeTimer);
            if (pointer_at_edge()) reveal(kBarStayMs);
        }
        return 0;
    case WM_MOUSEMOVE: {
        // A mouse's own move: the pointer is the mouse's again (a finger's moves are Windows' copies, marked).
        if (!from_touch()) g_bar_by_touch = false;
        // The chip under the pointer lights up as the game's green button.
        const int now = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
        if (now != g_bar_hover) {
            g_bar_hover = now;
            bar_frame();
        }
        return 0;
    }
    case WM_LBUTTONDOWN:
        // Held on a chip: it looks pressed, and the bar keeps the mouse until it is let go.
        g_bar_pressed = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
        g_bar_hover = g_bar_pressed;
        SetCapture(h);
        bar_frame();
        return 0;
    case WM_CAPTURECHANGED:
        // The mouse taken away while held (another window, a system dialog): nothing acts.
        if (g_bar_pressed != kNone) {
            g_bar_pressed = kNone;
            bar_frame();
        }
        return 0;
    case WM_LBUTTONUP: {
        const int chip = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
        // Only a chip let go of where it was pressed acts: a press slid off it, or onto it from elsewhere, does nothing.
        const int pressed = g_bar_pressed;
        g_bar_pressed = kNone;
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
        // The X asks before quitting; the full screen chip switches at once (the window redraws the bar for it).
        if (chip != pressed) return 0;
        if (chip == kQuitChip) ask_quit();
        else if (chip == kScreenChip && g_hooks.toggle_fullscreen) g_hooks.toggle_fullscreen();
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

// ---- the question before quitting

HWND g_ask = nullptr;
// Whether it is up, the button the keys chose (Keep playing first) and what is under the pointer.
bool g_asking = false;
constexpr int kKeep = 0, kQuit = 1, kClose = 2;
int g_choice = kKeep;
int g_ask_hover = kNone;
// What the mouse's button (or a finger) went down on: a button, the thin X, beside the card (kBeside), or kNone (the
// card's own body); only a release on the same acts, and a button held looks pressed in.
constexpr int kBeside = 3;
int g_ask_pressed = kNone;
// Whether the window is minimised with the game held for it, and whether the game is held now (for either).
bool g_minimised_hold = false, g_held = false;
// The question's picture, kept while the game's area keeps its size: at 4K it is 33 MB, made again only for a new size.
std::unique_ptr<Canvas> g_ask_canvas;
// What it was last drawn with (its choice, the pointer's place, the press, the scale): a move of the window with the
// same look only moves it.
int g_ask_drawn_choice = -1, g_ask_drawn_hover = -1, g_ask_drawn_pressed = -1;
float g_ask_drawn_scale = 0;

// The game held still while the question is up or the window is minimised, and let go on when neither is: the window
// is told only of a change.
void update_hold() {
    const bool want = g_asking || g_minimised_hold;
    if (want == g_held) return;
    g_held = want;
    if (g_hooks.hold) g_hooks.hold(want);
}

// The question's layout in a window w by h: the card in the middle, its header, its thin X, its two buttons.
struct AskLayout {
    RectF card, header, close, text, keep, quit;
};
AskLayout ask_layout(int w, int h) {
    // Within the game's area, however large Windows' scale.
    const AskScale cap;
    AskLayout l;
    // At 720 lines, as the game's own dialog there: 600 wide; the header 62 high, the glow's two pixels under it; the
    // line of text with 24 above and below it (26 for the line), then the buttons 220 by 56 side by side with 16
    // between, centred, and 24 under them.
    const float width = static_cast<float>(px(600)), head = static_cast<float>(px(62)), line = static_cast<float>(std::max(2, px(2)));
    const float text = static_cast<float>(px(74)), tall = static_cast<float>(px(56)), gap = static_cast<float>(px(16)), pad = static_cast<float>(px(24));
    const float each = static_cast<float>(px(220));
    const float height = head + line + text + tall + pad;
    // On whole pixels, so that its edges stay sharp.
    l.card = RectF(std::floor((static_cast<float>(w) - width) / 2), std::floor((static_cast<float>(h) - height) / 2), width, height);
    l.header = RectF(l.card.X, l.card.Y, width, head);
    // The thin X's square at the header's right end.
    l.close = RectF(l.card.X + width - head, l.card.Y, head, head);
    l.text = RectF(l.card.X + pad, l.card.Y + head + line, width - pad * 2, text);
    l.keep = RectF(std::floor(l.card.X + (width - each * 2 - gap) / 2), l.text.Y + text, each, tall);
    l.quit = RectF(l.keep.X + each + gap, l.keep.Y, each, tall);
    return l;
}

// The question's words in the language of the PC.
const wchar_t* ask_title() { return g_korean ? L"게임을 끝낼까요?" : L"Quit the game?"; }
// What quitting loses, true on any screen: the player cannot tell whether a song is going on.
const wchar_t* ask_text() { return g_korean ? L"곡 도중에 끝내면 기록이 남지 않아요." : L"Quitting mid-song loses that song's record."; }
const wchar_t* keep_label() { return g_korean ? L"계속하기" : L"Keep playing"; }
const wchar_t* quit_label() { return g_korean ? L"게임 끝내기" : L"Quit the game"; }

void draw_ask() {
    const RECT a = area();
    const int w = a.right - a.left, h = a.bottom - a.top;
    if (w <= 0 || h <= 0) return;
    // Within the game's area, however large Windows' scale: the card and all in it.
    const AskScale cap;
    // The same look at the same size: only its place on the screen changes.
    if (g_ask_canvas && g_ask_canvas->w == w && g_ask_canvas->h == h && g_ask_drawn_choice == g_choice && g_ask_drawn_hover == g_ask_hover &&
        g_ask_drawn_pressed == g_ask_pressed && g_ask_drawn_scale == scale()) {
        g_ask_canvas->show(g_ask, a.left, a.top, 255);
        return;
    }
    g_ask_drawn_choice = g_choice;
    g_ask_drawn_hover = g_ask_hover;
    g_ask_drawn_pressed = g_ask_pressed;
    g_ask_drawn_scale = scale();
    if (!g_ask_canvas || g_ask_canvas->w != w || g_ask_canvas->h != h) g_ask_canvas = std::make_unique<Canvas>(w, h);
    Canvas& c = *g_ask_canvas;
    {
        auto bmp = c.surface();
        Graphics g(bmp.get());
        // What the last picture had goes first.
        g.Clear(Color(0, 0, 0, 0));
        text_setup(g);
        // The game dimmed behind it, as the game dims itself behind its own dialogs.
        SolidBrush dim(Color(153, 0, 0, 0));
        g.FillRectangle(&dim, 0, 0, w, h);
        const AskLayout l = ask_layout(w, h);
        const float radius = static_cast<float>(px(4));
        // The buttons' corners, a little rounder than the card's, as the game's OK.
        const float button_radius = static_cast<float>(px(5));
        shadow(g, l.card, radius);
        // The card: its grey body, then its header within the card's corners.
        GraphicsPath card_path;
        rounded(card_path, l.card, radius);
        SolidBrush body(kBody);
        g.FillPath(&body, &card_path);
        g.SetClip(&card_path);
        SolidBrush header(kHeader.GetValue() | 0xFF000000);
        g.FillRectangle(&header, l.header);
        // The light line along its top, as the game's dialog has.
        Pen top_light(kTopLight, 1.0f);
        g.DrawLine(&top_light, l.card.X, l.card.Y + 0.5f, l.card.X + l.card.Width, l.card.Y + 0.5f);
        // The glow under the header.
        glow(g, l.card.X, l.header.Y + l.header.Height, l.card.Width);
        g.ResetClip();
        // The dark line around it, which keeps it apart from a dark game behind.
        GraphicsPath outline;
        rounded(outline, RectF(l.card.X - 0.5f, l.card.Y - 0.5f, l.card.Width + 1, l.card.Height + 1), radius + 0.5f);
        Pen dark(kOutline, 1.0f);
        g.DrawPath(&dark, &outline);
        // The title in the middle of the header, clear of the thin X at its right.
        const float side = l.close.Width;
        centred(g, ask_title(), static_cast<float>(px(24)), true, kText,
                RectF(l.header.X + side, l.header.Y, l.header.Width - side * 2, l.header.Height));
        // The thin X that closes it (keep playing): white, whole under the pointer, with a faint square behind it.
        if (g_ask_hover == kClose) {
            SolidBrush lit(Color(28, 255, 255, 255));
            const float inset = static_cast<float>(px(10));
            GraphicsPath spot;
            rounded(spot, RectF(l.close.X + inset, l.close.Y + inset, l.close.Width - inset * 2, l.close.Height - inset * 2), radius);
            g.FillPath(&lit, &spot);
        }
        Pen thin(g_ask_hover == kClose ? kText : Color(215, 255, 255, 255), 2.0f * scale());
        thin.SetStartCap(LineCapRound);
        thin.SetEndCap(LineCapRound);
        cross(g, thin, l.close.X + l.close.Width / 2, l.close.Y + l.close.Height / 2, static_cast<float>(px(9)));
        // The one quiet line that says what quitting loses.
        centred(g, ask_text(), static_cast<float>(px(18)), false, kQuiet, l.text);
        // Keep playing as the game's green button, Quit the game as a grey one; lighter under the pointer, pressed in
        // (deeper, darker at the top) while held there.
        const bool keep_lit = g_ask_hover == kKeep, quit_lit = g_ask_hover == kQuit;
        const bool keep_in = keep_lit && g_ask_pressed == kKeep, quit_in = quit_lit && g_ask_pressed == kQuit;
        button(g, l.keep, button_radius, keep_in ? kGreenPressedTop : keep_lit ? kGreenTopHover : kGreenTop,
               keep_in ? kGreenPressedBottom : keep_lit ? kGreenBottomHover : kGreenBottom, kGreenEdge);
        button(g, l.quit, button_radius, quit_in ? kGreyPressedTop : quit_lit ? kGreyTopHover : kGreyTop,
               quit_in ? kGreyPressedBottom : quit_lit ? kGreyBottomHover : kGreyBottom, kGreyEdge);
        centred(g, keep_label(), static_cast<float>(px(21)), true, kText, l.keep);
        centred(g, quit_label(), static_cast<float>(px(21)), true, kText, l.quit);
        // The keys' choice: a lime ring a little outside its button, plain to see for a person without a mouse.
        const RectF chosen = g_choice == kKeep ? l.keep : l.quit;
        const float out = static_cast<float>(px(3));
        GraphicsPath ring;
        rounded(ring, RectF(chosen.X - out, chosen.Y - out, chosen.Width + out * 2, chosen.Height + out * 2), button_radius + out);
        Pen lime(kChosen, static_cast<REAL>(std::max(2, px(2))));
        g.DrawPath(&lime, &ring);
    }
    c.show(g_ask, a.left, a.top, 255);
}

// What is under a point of the question's window: a button, the thin X, or kNone.
int ask_at(int x, int y) {
    const RECT a = area();
    const AskLayout l = ask_layout(a.right - a.left, a.bottom - a.top);
    const auto px_x = static_cast<REAL>(x), px_y = static_cast<REAL>(y);
    if (l.keep.Contains(px_x, px_y)) return kKeep;
    if (l.quit.Contains(px_x, px_y)) return kQuit;
    if (l.close.Contains(px_x, px_y)) return kClose;
    return kNone;
}
bool in_card(int x, int y) {
    const RECT a = area();
    return ask_layout(a.right - a.left, a.bottom - a.top).card.Contains(static_cast<REAL>(x), static_cast<REAL>(y));
}

// The question gone; the game goes on (unless minimised), or ends when `quit`.
void answer(bool quit) {
    if (!g_asking) return;
    g_asking = false;
    ShowWindow(g_ask, SW_HIDE);
    update_hold();
    if (quit && g_hooks.quit) g_hooks.quit();
}

LRESULT CALLBACK ask_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    const int x = static_cast<short>(LOWORD(l)), y = static_cast<short>(HIWORD(l));
    switch (msg) {
    case WM_MOUSEMOVE: {
        // The window hears when the pointer leaves it (off the game), to light nothing then.
        TRACKMOUSEEVENT t{sizeof t, TME_LEAVE, h, 0};
        TrackMouseEvent(&t);
        // What is under the pointer is lighter; the keys' choice stays where the keys put it.
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

// Text broken into lines of at most `room` pixels at its spaces, as Korean is set (GDI+ would break between any two
// Hangul syllables, leaving one alone on a line); a word longer than the room stays whole on its own line.
std::vector<std::wstring> wrap_words(Graphics& g, const std::wstring& text, const Font& font, float room) {
    std::vector<std::wstring> lines;
    std::wstring line;
    std::size_t at = 0;
    while (at <= text.size()) {
        std::size_t space = text.find(L' ', at);
        if (space == std::wstring::npos) space = text.size();
        const std::wstring word = text.substr(at, space - at);
        const std::wstring longer = line.empty() ? word : line + L" " + word;
        RectF box;
        g.MeasureString(longer.c_str(), -1, &font, PointF(0, 0), &box);
        if (box.Width <= room || line.empty()) {
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
std::vector<std::wstring> wrap_even(Graphics& g, const std::wstring& text, const Font& font, float room) {
    auto lines = wrap_words(g, text, font, room);
    if (lines.size() < 2) return lines;
    // Halving the room between what fits in that many lines and the full room, to within a pixel.
    float low = 0, high = room;
    while (high - low > 1) {
        const float mid = (low + high) / 2;
        if (wrap_words(g, text, font, mid).size() <= lines.size()) high = mid;
        else low = mid;
    }
    return wrap_words(g, text, font, high);
}

// The lines one under the other, as one text with line breaks.
std::wstring joined(const std::vector<std::wstring>& lines) {
    std::wstring out;
    for (std::size_t i = 0; i < lines.size(); ++i) out += (i ? L"\n" : L"") + lines[i];
    return out;
}

// The notice's picture for "title\ndetail": a small card of the game's dialog header (#1C1C1C, nearly square corners,
// the light line along its top, the lime glow along its bottom), the broadcast's mark as a pill on its left (red while
// live, grey once ended), the title in white bold and where to watch under it, quiet.
std::unique_ptr<Canvas> make_notice(const std::string& text, bool live) {
    const std::wstring all = wide(text);
    const std::size_t cut = all.find(L'\n');
    std::wstring title = all.substr(0, cut), detail = cut == std::wstring::npos ? L"" : all.substr(cut + 1);
    // The card's size from its text: the mark, then the title over the detail.
    const auto family = face(g_korean);
    Font title_font(family.get(), static_cast<REAL>(px(18)), FontStyleBold, UnitPixel);
    Font detail_font(family.get(), static_cast<REAL>(px(15)), FontStyleRegular, UnitPixel);
    Font mark_font(family.get(), static_cast<REAL>(px(13)), FontStyleBold, UnitPixel);
    const wchar_t* mark = live ? L"LIVE" : (g_korean ? L"방송 종료" : L"ENDED");
    // The room inside the card, between the mark and the words, the mark's dot, and the room around the card for its
    // shadow.
    const float pad = static_cast<float>(px(16)), gap = static_cast<float>(px(14)), dot = static_cast<float>(px(7));
    const float margin = static_cast<float>(px(10));
    // The glow's two pixels at the card's bottom, kept clear of the words.
    const float line = static_cast<float>(std::max(2, px(2)));
    RectF title_box, detail_box, mark_box;
    float mark_w = 0, room = 0;
    {
        // A one-pixel picture to measure the words on.
        Bitmap probe(1, 1, PixelFormat32bppPARGB);
        Graphics g(&probe);
        text_setup(g);
        g.MeasureString(mark, -1, &mark_font, PointF(0, 0), &mark_box);
        mark_w = mark_box.Width + dot + px(20);
        // The words' room: at most 680 pixels at 720 lines, and within the game's area however small its window; a long
        // server name wraps there.
        const RECT a = area();
        float beside = pad * 2 + mark_w + gap + margin * 2 + px(16);
        // A frame counter in a top corner keeps its corner: the card, centred, stays clear of it on both sides.
        if (g_fps_corner == 1 || g_fps_corner == 2) {
            // How far in from its side the counter reaches (top left, beside the pause button), on both sides.
            auto counter = make_fps(-1, 0);
            const POINT at = fps_place(*counter);
            const float reach = g_fps_corner == 1 ? static_cast<float>(at.x - a.left + counter->w) : static_cast<float>(a.right - at.x);
            beside += 2.0f * (reach + static_cast<float>(px(8)));
        }
        room = std::max(static_cast<float>(px(160)), std::min(static_cast<float>(px(680)), static_cast<float>(a.right - a.left) - beside));
        // Each line broken at its spaces within the room, then measured as the lines it became.
        title = joined(wrap_even(g, title, title_font, room));
        if (!detail.empty()) detail = joined(wrap_even(g, detail, detail_font, room));
        g.MeasureString(title.c_str(), -1, &title_font, PointF(0, 0), &title_box);
        if (!detail.empty()) g.MeasureString(detail.c_str(), -1, &detail_font, PointF(0, 0), &detail_box);
    }
    const float mark_h = static_cast<float>(px(26));
    const float text_w = std::max(title_box.Width, detail_box.Width);
    const float text_h = title_box.Height + (detail.empty() ? 0 : detail_box.Height + px(2));
    const int w = static_cast<int>(std::ceil(pad * 2 + mark_w + gap + text_w + margin * 2));
    const int h = static_cast<int>(std::ceil(pad * 2 + line + std::max(text_h, mark_h) + margin * 2));
    auto canvas = std::make_unique<Canvas>(w, h);
    {
        auto bmp = canvas->surface();
        Graphics g(bmp.get());
        text_setup(g);
        // The card on whole pixels, its shadow under it.
        const RectF box(margin, margin, std::floor(w - margin * 2), std::floor(h - margin * 2));
        const float radius = static_cast<float>(px(4));
        shadow(g, box, radius);
        GraphicsPath card_path;
        rounded(card_path, box, radius);
        SolidBrush header(kHeader);
        g.FillPath(&header, &card_path);
        // The light line along its top and the glow along its bottom, within its corners.
        g.SetClip(&card_path);
        Pen top_light(kTopLight, 1.0f);
        g.DrawLine(&top_light, box.X, box.Y + 0.5f, box.X + box.Width, box.Y + 0.5f);
        glow(g, box.X, box.Y + box.Height - line, box.Width);
        g.ResetClip();
        // The dark line around it, which keeps it apart from a dark game behind.
        GraphicsPath outline;
        rounded(outline, RectF(box.X - 0.5f, box.Y - 0.5f, box.Width + 1, box.Height + 1), radius + 0.5f);
        Pen dark(kOutline, 1.0f);
        g.DrawPath(&dark, &outline);
        // The inside of the card above the glow: the mark and the words are centred in it.
        const float inside = box.Height - line;
        // The mark: a pill with a dot, red while live.
        const RectF pill(box.X + pad, box.Y + (inside - mark_h) / 2, mark_w, mark_h);
        GraphicsPath path;
        rounded(path, pill, mark_h / 2);
        SolidBrush pill_fill(live ? kLive : kEnded);
        g.FillPath(&pill_fill, &path);
        SolidBrush white(kText);
        g.FillEllipse(&white, pill.X + px(9), pill.Y + (mark_h - dot) / 2, dot, dot);
        StringFormat middle;
        middle.SetLineAlignment(StringAlignmentCenter);
        g.DrawString(mark, -1, &mark_font, RectF(pill.X + px(9) + dot + px(5), pill.Y, mark_box.Width + px(4), mark_h), &middle, &white);
        // The title, and where to watch under it.
        const float tx = pill.X + mark_w + gap, ty = box.Y + (inside - text_h) / 2;
        SolidBrush quiet(kQuiet);
        // Their lines as broken above: drawn as they were measured.
        g.DrawString(title.c_str(), -1, &title_font, PointF(tx, ty), &white);
        if (!detail.empty()) g.DrawString(detail.c_str(), -1, &detail_font, PointF(tx, ty + title_box.Height + px(2)), &quiet);
    }
    return canvas;
}

}  // namespace

void start(HWND frame, HWND game, const Hooks& hooks, bool korean) {
    g_frame = frame;
    g_game = game;
    g_hooks = hooks;
    g_korean = korean;
    GdiplusStartupInput input;
    GdiplusStartup(&g_gdiplus, &input, nullptr);
    // The notice and the frame counter let clicks through to the game; the bar and the question take theirs. The counter
    // first, so that the windows made after it are above it.
    g_fps = make_window(L"OpenDMTQFrameCounter", fps_proc, true);
    g_notice = make_window(L"OpenDMTQNotice", notice_proc, true);
    g_bar = make_window(L"OpenDMTQBar", bar_proc, false);
    g_ask = make_window(L"OpenDMTQQuestion", ask_proc, false);
}

void notice(const std::string& text, bool live) {
    if (!g_notice) return;
    g_notice_canvas = make_notice(text, live);
    // From its first step, sliding in.
    g_notice_shown = GetTickCount64();
    notice_frame();
    ShowWindow(g_notice, SW_SHOWNOACTIVATE);
    SetTimer(g_notice, kNoticeTimer, 15, nullptr);
}

void pointer_moved(int y, bool pressed) {
    g_pointer_down = pressed;
    // Not while the mouse plays (its button down), not over the question, and only at the very top edge of the game
    // (within 4 pixels at 720 lines): the game's own controls under the bar's place stay the game's while they are used.
    if (!g_bar || asking() || pressed) return;
    // A mouse's move: the pointer is the mouse's again.
    g_bar_by_touch = false;
    if (y >= std::max(1, px(4))) return;
    // Up already: it stays. Else the edge waits a moment, and the bar shows only if the pointer is still there then.
    if (IsWindowVisible(g_bar)) reveal(kBarStayMs);
    else SetTimer(g_bar, kBarEdgeTimer, kBarEdgeMs, nullptr);
}


void show_bar() {
    if (!g_bar || asking()) return;
    // A finger has no pointer that stays on the bar: whole for a few seconds, then fading.
    g_bar_by_touch = true;
    reveal(kBarTouchStayMs);
}

bool asking() { return g_ask && g_asking; }

void ask_quit() {
    if (!g_ask || g_asking) return;
    g_asking = true;
    // Keep playing chosen first, so that Enter at once goes on; nothing lit until the pointer moves over it.
    g_choice = kKeep;
    g_ask_hover = kNone;
    g_ask_pressed = kNone;
    hide_bar();
    // The game held before anything else happens to it (minimised, it is held already).
    update_hold();
    // Over a minimised game it would show nowhere: the game comes back first, still held for the question.
    if (IsIconic(g_frame)) ShowWindow(g_frame, SW_RESTORE);
    draw_ask();
    ShowWindow(g_ask, SW_SHOWNOACTIVATE);
    // Above everything else of the overlay: the frame counter stays, under its dim.
    SetWindowPos(g_ask, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
}

void minimised(bool now) {
    if (now) {
        // Minimised mid-song: the game holds still as a phone's does when its owner leaves it; the bar goes with it.
        g_minimised_hold = true;
        hide_bar();
    } else {
        // Back: the game goes on (to its own pause screen mid-song), unless the question is up.
        g_minimised_hold = false;
    }
    update_hold();
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
    // The question over the game's area as it is now.
    if (asking()) draw_ask();
    // The bar across the game's top at its new width, if it is up.
    if (g_bar && IsWindowVisible(g_bar)) bar_frame();
    if (g_notice_canvas) notice_frame();
    // The frame counter in its corner, at the new scale (a move counts nothing: its numbers stay its timer's).
    fps_place_now();
}

void show_fps(int corner, FrameCount (*frames)()) {
    if (!g_fps || corner <= 0 || corner > 4 || !frames) return;
    g_fps_corner = corner;
    g_fps_frames = frames;
    // Shown at once, with dashes until the first half second has been counted.
    fps_frame();
    ShowWindow(g_fps, SW_SHOWNOACTIVATE);
    SetTimer(g_fps, kFpsTimer, kFpsMs, nullptr);
}

#ifdef OVERLAY_TEST_HOOKS
// For the overlay's own probe only (_work/winprobe): the bar, the question and the notice as PNGs with their own
// transparency, drawn into pictures whose windows stay hidden (nothing here shows one): a locked or busy screen cannot
// be captured, and a check shows nothing on it.
void test_save(const std::wstring& prefix) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    auto save = [&](Canvas& c, const std::wstring& name) {
        // The premultiplied picture into a plain one with its alpha, which PNG keeps.
        Bitmap out(c.w, c.h, PixelFormat32bppARGB);
        Graphics g(&out);
        g.Clear(Color(0, 0, 0, 0));
        g.SetCompositingMode(CompositingModeSourceCopy);
        auto picture = c.surface();
        g.DrawImage(picture.get(), 0, 0, c.w, c.h);
        out.Save((prefix + name).c_str(), &png, nullptr);
    };
    const Hooks kept = g_hooks;
    // The bar in a window and in full screen (its chip's icon the other way), at rest and with each chip lit.
    for (bool full : {false, true}) {
        g_hooks.fullscreen = full ? +[] { return true; } : +[] { return false; };
        const std::wstring state = full ? L"full" : L"window";
        for (int which : {kNone, kScreenChip, kQuitChip}) {
            g_bar_hover = which;
            const wchar_t* lit = which == kNone ? L"" : which == kScreenChip ? L"-screen" : L"-quit";
            save(bar_canvas(), L"bar-" + state + lit + L".png");
        }
        // Each chip held down under the pointer.
        for (int which : {kScreenChip, kQuitChip}) {
            g_bar_hover = g_bar_pressed = which;
            save(bar_canvas(), L"bar-" + state + (which == kScreenChip ? L"-screen" : L"-quit") + L"-pressed.png");
        }
        g_bar_pressed = kNone;
    }
    g_hooks = kept;
    g_bar_hover = kNone;
    // The question with each choice of the keys, then the pointer on each button and on the thin X; drawn into its
    // window's picture, which stays hidden (only ask_quit shows it).
    struct Look {
        int choice, hover;
        const wchar_t* name;
    };
    for (const Look& look : {Look{kKeep, kNone, L"ask-keep.png"}, Look{kQuit, kNone, L"ask-quit.png"}, Look{kKeep, kKeep, L"ask-hover-keep.png"},
                             Look{kKeep, kQuit, L"ask-hover-quit.png"}, Look{kKeep, kClose, L"ask-hover-close.png"}}) {
        g_choice = look.choice;
        g_ask_hover = look.hover;
        draw_ask();
        save(*g_ask_canvas, look.name);
    }
    // Each button held down under the pointer.
    for (int which : {kKeep, kQuit}) {
        g_ask_hover = g_ask_pressed = which;
        draw_ask();
        save(*g_ask_canvas, which == kKeep ? L"ask-pressed-keep.png" : L"ask-pressed-quit.png");
    }
    g_ask_pressed = kNone;
    g_choice = kKeep;
    g_ask_hover = kNone;
    // The notice while live and once ended, in the server's own words (server/game/live/state.php), a server's name in
    // its place.
    const std::string live_text = g_korean ? "이 플레이를 방송하고 있어요\nMy Server 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Your play is live\nWatch it now or later under LIVE on My Server";
    const std::string ended_text = g_korean ? "방송을 마쳤어요\nMy Server 사이트 LIVE에서 다시 볼 수 있어요"
                                            : "Your broadcast has ended\nWatch the replay under LIVE on My Server";
    save(*make_notice(live_text, true), L"notice-live.png");
    save(*make_notice(ended_text, false), L"notice-ended.png");
    // A server whose name is long, which the card wraps within the game's width.
    const std::string long_text = g_korean ? "이 플레이를 방송하고 있어요\nOpenDMTQ Community Server Seoul Central 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Your play is live\nWatch it now or later under LIVE on OpenDMTQ Community Server Seoul Central";
    save(*make_notice(long_text, true), L"notice-long.png");
    // The same with a counter in a top corner, which the card keeps clear of.
    const int corner_before = g_fps_corner;
    for (int corner : {1, 2}) {
        g_fps_corner = corner;
        save(*make_notice(long_text, true), corner == 1 ? L"notice-long-fps1.png" : L"notice-long-fps2.png");
    }
    g_fps_corner = corner_before;
    // The frame counter before its first half second, with the game held, at 60, at 240 and at its most.
    struct Count {
        int fps;
        float ms;
        const wchar_t* name;
    };
    for (const Count& n : {Count{-1, 0, L"fps-dash.png"}, Count{0, 0, L"fps-0.png"}, Count{60, 16.7f, L"fps-60.png"}, Count{240, 4.2f, L"fps-240.png"},
                           Count{999, 1.0f, L"fps-999.png"}}) {
        save(*make_fps(n.fps, n.ms), n.name);
    }
    // Where each is placed in the game's area, from the same code that places their windows: "name x y w h" a line.
    FILE* out = _wfopen((prefix + L"layout.txt").c_str(), L"w");
    if (!out) return;
    const RECT a = area();
    std::fprintf(out, "area 0 0 %ld %ld\nscale %.4f\n", a.right - a.left, a.bottom - a.top, static_cast<double>(scale()));
    std::fprintf(out, "bar 0 0 %ld %d\n", a.right - a.left, bar_height());
    for (const auto& [name, live] : {std::pair<const char*, bool>{"notice-live", true}, {"notice-ended", false}, {"notice-long", true}}) {
        auto c = make_notice(std::string(name) == "notice-long" ? long_text : live ? live_text : ended_text, live);
        const POINT at = notice_place(*c);
        std::fprintf(out, "%s %ld %ld %d %d\n", name, at.x - a.left, at.y - a.top, c->w, c->h);
    }
    for (int corner : {1, 2}) {
        g_fps_corner = corner;
        auto c = make_notice(long_text, true);
        g_fps_corner = corner_before;
        const POINT at = notice_place(*c);
        std::fprintf(out, "notice-long-fps%d %ld %ld %d %d\n", corner, at.x - a.left, at.y - a.top, c->w, c->h);
    }
    const int kept_corner = g_fps_corner;
    for (int corner = 1; corner <= 4; ++corner) {
        g_fps_corner = corner;
        auto c = make_fps(240, 4.2f);
        const POINT at = fps_place(*c);
        std::fprintf(out, "fps%d %ld %ld %d %d\n", corner, at.x - a.left, at.y - a.top, c->w, c->h);
    }
    // The same with the bar up: the notice and a counter in a top corner under it.
    g_test_bar_up = true;
    for (int corner = 1; corner <= 2; ++corner) {
        g_fps_corner = corner;
        auto c = make_fps(240, 4.2f);
        const POINT at = fps_place(*c);
        std::fprintf(out, "fps%d-bar %ld %ld %d %d\n", corner, at.x - a.left, at.y - a.top, c->w, c->h);
    }
    // The notices as without a counter.
    g_fps_corner = kept_corner;
    for (const auto& [name, live] : {std::pair<const char*, bool>{"notice-live", true}, {"notice-long", true}}) {
        auto c = make_notice(std::string(name) == "notice-long" ? long_text : live_text, live);
        const POINT at = notice_place(*c);
        std::fprintf(out, "%s-bar %ld %ld %d %d\n", name, at.x - a.left, at.y - a.top, c->w, c->h);
    }
    g_test_bar_up = false;
    g_fps_corner = kept_corner;
    const AskLayout l = ask_layout(a.right - a.left, a.bottom - a.top);
    std::fprintf(out, "card %.0f %.0f %.0f %.0f\n", l.card.X, l.card.Y, l.card.Width, l.card.Height);
    std::fprintf(out, "keep %.0f %.0f %.0f %.0f\nquit %.0f %.0f %.0f %.0f\n", l.keep.X, l.keep.Y, l.keep.Width, l.keep.Height, l.quit.X, l.quit.Y,
                 l.quit.Width, l.quit.Height);
    for (int which : {kScreenChip, kQuitChip}) {
        const RectF r = chip_rect(which, a.right - a.left);
        std::fprintf(out, "%s %.0f %.0f %.0f %.0f\n", which == kQuitChip ? "chip-quit" : "chip-screen", r.X, r.Y, r.Width, r.Height);
    }
    std::fclose(out);
}

void test_set_dpi(float scale) { g_test_dpi = scale; }
#endif

#ifdef OVERLAY_TEST_HOOKS
void test_save_fps(const std::wstring& path, int fps, float ms) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    auto c = make_fps(fps, ms);
    // The premultiplied picture into a plain one with its alpha, which PNG keeps.
    Bitmap out(c->w, c->h, PixelFormat32bppARGB);
    Graphics g(&out);
    g.Clear(Color(0, 0, 0, 0));
    g.SetCompositingMode(CompositingModeSourceCopy);
    auto picture = c->surface();
    g.DrawImage(picture.get(), 0, 0, c->w, c->h);
    out.Save(path.c_str(), &png, nullptr);
}
#endif

HCURSOR cursor(bool pressed) {
    static std::map<std::pair<int, bool>, HCURSOR> made;
    // Windows' own cursor size at this scale: 32 pixels at 96 dpi, 48 at 150 % (Windows' scale alone, as its own
    // pointer's).
    const int size = std::max(32, static_cast<int>(std::lround(32 * dpi_scale())));
    HCURSOR& c = made[{size, pressed}];
    if (!c) c = make_cursor(size, pressed);
    return c;
}

}  // namespace player::overlay
