// What the player for Windows draws over the game itself (window_win32.cpp places and feeds it), in OpenDMTQ's own look:
// dark opaque surfaces with rounded corners and a thin light edge, white text, and colour only where it means something
// (red for a live broadcast and for quitting). Each is a layered window of its own above the game's window, drawn with
// GDI+ into a premultiplied 32-bit bitmap and shown with UpdateLayeredWindow, so its edges are smooth and its fades
// cost the game nothing.
//
// - The notice: the server's two-line notice about a broadcast (a title, then where to watch), as a card that slides
//   down at the top of the game, stays for a few seconds and fades. A red LIVE mark while broadcasting, a grey one when
//   the broadcast has ended.
// - The menu: a PC has no phone's buttons around the game, so a small round button shows at the top right while the
//   mouse moves and opens a menu: back to the game, full screen or a window, quit (the only way out: Alt+F4 and the
//   window's X open it too). Holding Esc and, on a touch screen, a finger drawn down from the top edge open it as well.
// - The cursor: a dart in the logo's chrome and lime, all lime while the mouse's finger is down on the game.
#include "overlay_win32.h"

#include <windows.h>
// GDI+ needs COM's object types, which the lean Windows headers this build asks for leave out.
#include <objidl.h>
// GDI+ uses min and max unqualified.
#include <algorithm>
namespace Gdiplus {
using std::max;
using std::min;
}  // namespace Gdiplus
#include <gdiplus.h>

#include <cmath>
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

// The look, at 96 dpi: the surfaces, the lines and the text.
const Color kSurface(250, 27, 30, 35);
const Color kRaised(255, 42, 47, 55);
const Color kRaisedHover(255, 54, 60, 70);
const Color kChosen(255, 140, 242, 61);   // the ring of the row the keys or the pointer chose: the logo's lime
const Color kEdge(40, 255, 255, 255);
const Color kText(255, 243, 244, 246);
const Color kQuiet(255, 174, 180, 190);
const Color kLive(255, 209, 58, 64);    // #D13A40: white bold text on it at 4.8:1
const Color kEnded(255, 108, 116, 128);
const Color kQuit(255, 255, 122, 122);
// The face: Windows' own for Korean, else its UI face; whatever sans face there is where neither is (Wine).
std::unique_ptr<FontFamily> face() {
    for (const wchar_t* name : {g_korean ? L"Malgun Gothic" : L"Segoe UI", L"Malgun Gothic", L"Segoe UI"}) {
        auto family = std::make_unique<FontFamily>(name);
        if (family->IsAvailable()) return family;
    }
    return std::unique_ptr<FontFamily>(FontFamily::GenericSansSerif()->Clone());
}

// The scale of the game's display (Windows' own, 1 at 96 dpi).
float dpi_scale() {
    using DpiOf = UINT(WINAPI*)(HWND);
    static auto dpi_of = reinterpret_cast<DpiOf>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"));
    return (dpi_of && g_frame ? static_cast<float>(dpi_of(g_frame)) : 96.0f) / 96.0f;
}
RECT area();
// The overlay's scale: Windows' own, or the game's when that is larger (a 4K display at 100 %, where the game draws its
// own buttons twice as large as at 1080 lines), so that the menu and the notice keep their size beside the game's.
float scale() {
    const RECT a = area();
    return std::max(dpi_scale(), static_cast<float>(a.bottom - a.top) / 1080.0f);
}
int px(float at96) { return static_cast<int>(std::lround(at96 * scale())); }

std::wstring wide(const std::string& s) {
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

// A rounded rectangle as a path.
void rounded(GraphicsPath& path, RectF r, float radius) {
    const float d = std::min(radius * 2, std::min(r.Width, r.Height));
    path.AddArc(r.X, r.Y, d, d, 180, 90);
    path.AddArc(r.X + r.Width - d, r.Y, d, d, 270, 90);
    path.AddArc(r.X + r.Width - d, r.Y + r.Height - d, d, d, 0, 90);
    path.AddArc(r.X, r.Y + r.Height - d, d, d, 90, 90);
    path.CloseFigure();
}

// A card: a soft shadow under it, the surface, a thin light edge.
void card(Graphics& g, RectF r, float radius, const Color& fill) {
    for (int i = 3; i >= 1; --i) {
        GraphicsPath shadow;
        const float grow = static_cast<float>(px(2.0f * i));
        rounded(shadow, RectF(r.X - grow, r.Y - grow + px(2), r.Width + grow * 2, r.Height + grow * 2), radius + grow);
        SolidBrush b(Color(static_cast<BYTE>(14 * (4 - i)), 0, 0, 0));
        g.FillPath(&b, &shadow);
    }
    GraphicsPath path;
    rounded(path, r, radius);
    SolidBrush surface(fill);
    g.FillPath(&surface, &path);
    Pen edge(kEdge, 1.0f);
    g.DrawPath(&edge, &path);
}

// A layered window's picture: a 32-bit premultiplied DIB that GDI+ draws into and UpdateLayeredWindow shows.
struct Canvas {
    HDC dc = nullptr;
    HBITMAP bitmap = nullptr;
    HGDIOBJ old = nullptr;
    void* bits = nullptr;
    int w = 0, h = 0;
    Canvas(int width, int height) : w(width), h(height) {
        BITMAPINFO info{};
        info.bmiHeader.biSize = sizeof info.bmiHeader;
        info.bmiHeader.biWidth = w;
        info.bmiHeader.biHeight = -h;
        info.bmiHeader.biPlanes = 1;
        info.bmiHeader.biBitCount = 32;
        dc = CreateCompatibleDC(nullptr);
        bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
        old = SelectObject(dc, bitmap);
    }
    ~Canvas() {
        SelectObject(dc, old);
        DeleteObject(bitmap);
        DeleteDC(dc);
    }
    // GDI+ over the same pixels, smooth shapes and text.
    std::unique_ptr<Bitmap> surface() { return std::make_unique<Bitmap>(w, h, w * 4, PixelFormat32bppPARGB, static_cast<BYTE*>(bits)); }
    // Shown at (x, y) on the screen, at `alpha` as a whole.
    void show(HWND window, int x, int y, BYTE alpha) {
        POINT at{x, y}, from{0, 0};
        SIZE size{w, h};
        BLENDFUNCTION blend{AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA};
        UpdateLayeredWindow(window, nullptr, &at, &size, dc, &from, 0, &blend, ULW_ALPHA);
    }
};

void text_setup(Graphics& g) {
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    g.SetPixelOffsetMode(PixelOffsetModeHalf);
}

// The game's area on the screen.
RECT area() {
    RECT r{};
    GetWindowRect(g_game ? g_game : g_frame, &r);
    return r;
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
    const DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | (see_through ? WS_EX_TRANSPARENT : 0);
    return CreateWindowExW(ex, name, L"", WS_POPUP, 0, 0, 1, 1, g_frame, nullptr, c.hInstance, nullptr);
}

// ---- the notice

HWND g_notice = nullptr;
std::unique_ptr<Canvas> g_notice_canvas;
UINT64 g_notice_shown = 0;  // GetTickCount64 when it came
constexpr UINT_PTR kNoticeTimer = 1;
constexpr UINT64 kSlideMs = 220, kStayMs = 6000, kFadeMs = 350;

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
    const RECT a = area();
    const int x = (a.left + a.right - g_notice_canvas->w) / 2;
    const int y = a.top + px(14) - static_cast<int>(drop);
    g_notice_canvas->show(g_notice, x, y, static_cast<BYTE>(alpha * 255));
    // The next step: every 15 ms while it slides or fades; while it stays, once, when the fade begins.
    const bool staying = t >= kSlideMs && t < kSlideMs + kStayMs;
    SetTimer(g_notice, kNoticeTimer, staying ? static_cast<UINT>(kSlideMs + kStayMs - t) : 15, nullptr);
}

LRESULT CALLBACK notice_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_TIMER && w == kNoticeTimer) {
        notice_frame();
        return 0;
    }
    if (msg == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(h, msg, w, l);
}

// ---- the menu button and the menu

HWND g_button = nullptr, g_menu = nullptr;
bool g_button_hover = false;
UINT64 g_moved = 0;  // when the mouse last moved over the game
// The button's one timer: due when its fade begins, then at each step of the fade.
constexpr UINT_PTR kButtonTimer = 2;
// Whole for this long after the mouse moved, then fading out over the next, a step at a time.
constexpr UINT64 kButtonStayMs = 2500, kButtonFadeMs = 400, kButtonStepMs = 30;
// The button's picture, kept while it looks the same (the pointer on it or not, the overlay's scale): its fade and its
// moves with the game show the same picture at another opacity or place (Canvas::show), as the notice's do.
std::unique_ptr<Canvas> g_button_canvas;
bool g_button_canvas_hover = false;
float g_button_canvas_scale = 0;
int g_menu_hover = -1;
// Where the pointer was in the menu's window as it came: the move Windows reports for a window that just showed is no
// choice of a row.
POINT g_menu_opened_at{-1, -1};
// The game was minimised: the menu is due (the game held still) and shows once the game is back.
bool g_menu_pending = false;
// The menu's picture, kept while the game's area keeps its size: at 4K it is 33 MB, made again only for a new size.
std::unique_ptr<Canvas> g_menu_canvas;

struct Item {
    std::wstring label;
    bool quit;
};
std::vector<Item> items() {
    const bool full = g_hooks.fullscreen && g_hooks.fullscreen();
    if (g_korean) return {{L"게임으로 돌아가기", false}, {full ? L"창 모드로" : L"전체 화면으로", false}, {L"게임 끝내기", true}};
    return {{L"Back to the game", false}, {full ? L"Windowed" : L"Full screen", false}, {L"Quit the game", true}};
}

// The menu's layout in its window: the card and each item's row.
struct Layout {
    RectF card;
    std::vector<RectF> rows;
};
Layout menu_layout(int w, int h) {
    Layout l;
    const float width = static_cast<float>(px(300)), row = static_cast<float>(px(46)), gap = static_cast<float>(px(8)),
                pad = static_cast<float>(px(18)), head = static_cast<float>(px(44)), foot = static_cast<float>(px(30));
    const auto n = static_cast<float>(items().size());
    const float height = pad + head + n * row + (n - 1) * gap + foot + pad;
    l.card = RectF((w - width) / 2, (h - height) / 2, width, height);
    for (std::size_t i = 0; i < items().size(); ++i)
        l.rows.emplace_back(l.card.X + pad, l.card.Y + pad + head + static_cast<float>(i) * (row + gap), width - pad * 2, row);
    return l;
}

// The button's picture as it looks now, drawn only when its look changed.
Canvas& button_canvas() {
    const float now_scale = scale();
    if (g_button_canvas && g_button_canvas_hover == g_button_hover && g_button_canvas_scale == now_scale) return *g_button_canvas;
    const int size = px(38);
    g_button_canvas = std::make_unique<Canvas>(size + px(12), size + px(12));
    g_button_canvas_hover = g_button_hover;
    g_button_canvas_scale = now_scale;
    {
        auto bmp = g_button_canvas->surface();
        Graphics g(bmp.get());
        text_setup(g);
        const float o = static_cast<float>(px(6));
        GraphicsPath circle;
        circle.AddEllipse(o, o, static_cast<float>(size), static_cast<float>(size));
        SolidBrush shadow(Color(40, 0, 0, 0));
        g.TranslateTransform(0, static_cast<float>(px(2)));
        g.FillPath(&shadow, &circle);
        g.ResetTransform();
        SolidBrush fill(g_button_hover ? kRaisedHover : kSurface);
        g.FillPath(&fill, &circle);
        Pen edge(kEdge, 1.0f);
        g.DrawPath(&edge, &circle);
        // Three short lines: a menu.
        Pen line(kText, static_cast<float>(px(2)));
        line.SetStartCap(LineCapRound);
        line.SetEndCap(LineCapRound);
        const float cx = o + size / 2.0f, cy = o + size / 2.0f, half = static_cast<float>(px(8)), step = static_cast<float>(px(5));
        for (int i = -1; i <= 1; ++i) g.DrawLine(&line, cx - half, cy + i * step, cx + half, cy + i * step);
    }
    return *g_button_canvas;
}

// The button at the game's top right at the opacity its time gives it (whole under the pointer, and for kButtonStayMs
// after the mouse moved, then fading over kButtonFadeMs), or hidden once it faded or while the menu is up; its one timer
// set for its next change.
void show_button() {
    const UINT64 idle = GetTickCount64() - g_moved;
    float alpha = 1;
    if (!g_button_hover && idle > kButtonStayMs) alpha = 1 - std::min(1.0f, static_cast<float>(idle - kButtonStayMs) / kButtonFadeMs);
    if (alpha <= 0 || menu_open()) {
        ShowWindow(g_button, SW_HIDE);
        KillTimer(g_button, kButtonTimer);
        return;
    }
    // The kept picture, shown again at this opacity and where the game's area is now.
    Canvas& c = button_canvas();
    const int margin = px(14);
    const RECT a = area();
    c.show(g_button, a.right - c.w - margin + px(6), a.top + margin - px(6), static_cast<BYTE>(alpha * 255));
    ShowWindow(g_button, SW_SHOWNOACTIVATE);
    // Under the pointer it stays as it is with no timer (leaving it starts its time again, button_proc); otherwise the
    // timer wakes it when its fade begins, and every step of the fade after.
    if (g_button_hover) KillTimer(g_button, kButtonTimer);
    else SetTimer(g_button, kButtonTimer, static_cast<UINT>(idle < kButtonStayMs ? kButtonStayMs - idle : kButtonStepMs), nullptr);
}

void draw_menu() {
    const RECT a = area();
    const int w = a.right - a.left, h = a.bottom - a.top;
    if (w <= 0 || h <= 0) return;
    if (!g_menu_canvas || g_menu_canvas->w != w || g_menu_canvas->h != h) g_menu_canvas = std::make_unique<Canvas>(w, h);
    Canvas& c = *g_menu_canvas;
    {
        auto bmp = c.surface();
        Graphics g(bmp.get());
        // What the last picture had goes first.
        g.Clear(Color(0, 0, 0, 0));
        text_setup(g);
        // The game dimmed behind it.
        SolidBrush dim(Color(150, 0, 0, 0));
        g.FillRectangle(&dim, 0, 0, w, h);
        const Layout l = menu_layout(w, h);
        card(g, l.card, static_cast<float>(px(16)), kSurface);
        const auto family = face();
        Font title(family.get(), static_cast<REAL>(px(15)), FontStyleBold, UnitPixel);
        Font label(family.get(), static_cast<REAL>(px(14)), FontStyleBold, UnitPixel);
        Font hint(family.get(), static_cast<REAL>(px(11.5f)), FontStyleRegular, UnitPixel);
        SolidBrush text(kText), quiet(kQuiet), quit(kQuit);
        StringFormat centre;
        centre.SetAlignment(StringAlignmentCenter);
        centre.SetLineAlignment(StringAlignmentCenter);
        const float pad = static_cast<float>(px(18));
        g.DrawString(L"OpenDMTQ", -1, &title, RectF(l.card.X, l.card.Y + pad, l.card.Width, static_cast<REAL>(px(30))), &centre, &text);
        const auto list = items();
        for (std::size_t i = 0; i < list.size(); ++i) {
            GraphicsPath row;
            rounded(row, l.rows[i], static_cast<float>(px(11)));
            const bool chosen = static_cast<int>(i) == g_menu_hover;
            SolidBrush fill(chosen ? kRaisedHover : kRaised);
            g.FillPath(&fill, &row);
            // The chosen row is plain to see, for the keys too: a ring of the lime.
            if (chosen) {
                Pen ring(kChosen, static_cast<REAL>(px(2)));
                g.DrawPath(&ring, &row);
            }
            g.DrawString(list[i].label.c_str(), -1, &label, l.rows[i], &centre, list[i].quit ? &quit : &text);
        }
        const wchar_t* keys = g_korean ? L"방향키와 Enter로 고르고 Esc로 닫아요" : L"Arrow keys and Enter to choose, Esc to close";
        g.DrawString(keys, -1, &hint, RectF(l.card.X, l.card.Y + l.card.Height - pad - px(26), l.card.Width, static_cast<REAL>(px(26))), &centre, &quiet);
    }
    c.show(g_menu, a.left, a.top, 255);
}

// The item under a point of the menu's window, or -1.
int item_at(int x, int y) {
    const RECT a = area();
    const Layout l = menu_layout(a.right - a.left, a.bottom - a.top);
    for (std::size_t i = 0; i < l.rows.size(); ++i)
        if (l.rows[i].Contains(static_cast<REAL>(x), static_cast<REAL>(y))) return static_cast<int>(i);
    return -1;
}
bool in_card(int x, int y) {
    const RECT a = area();
    return menu_layout(a.right - a.left, a.bottom - a.top).card.Contains(static_cast<REAL>(x), static_cast<REAL>(y));
}

void choose(int i) {
    close_menu();
    if (i == 1 && g_hooks.toggle_fullscreen) g_hooks.toggle_fullscreen();
    if (i == 2 && g_hooks.quit) g_hooks.quit();
}

LRESULT CALLBACK button_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_TIMER:
        if (w == kButtonTimer) show_button();
        return 0;
    case WM_MOUSEMOVE:
        if (!g_button_hover) {
            g_button_hover = true;
            TRACKMOUSEEVENT t{sizeof t, TME_LEAVE, h, 0};
            TrackMouseEvent(&t);
            show_button();
        }
        return 0;
    case WM_MOUSELEAVE:
        g_button_hover = false;
        g_moved = GetTickCount64();
        show_button();
        return 0;
    case WM_LBUTTONUP:
        SetForegroundWindow(g_frame);
        open_menu();
        return 0;
    case WM_SETCURSOR:
        // The game's pointer over the button too.
        SetCursor(cursor(false));
        return TRUE;
    case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

LRESULT CALLBACK menu_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    const int x = static_cast<short>(LOWORD(l)), y = static_cast<short>(HIWORD(l));
    switch (msg) {
    case WM_MOUSEMOVE: {
        // The move Windows reports as the menu shows, with the pointer where it was: the keys' choice stays.
        if (x == g_menu_opened_at.x && y == g_menu_opened_at.y) return 0;
        g_menu_opened_at = POINT{-1, -1};
        const int hover = item_at(x, y);
        if (hover != g_menu_hover) {
            g_menu_hover = hover;
            draw_menu();
        }
        return 0;
    }
    case WM_LBUTTONUP: {
        // The keyboard back to the game's window: the menu never takes it, another program may have.
        SetForegroundWindow(g_frame);
        const int i = item_at(x, y);
        if (i >= 0) choose(i);
        // A press beside the card is back to the game.
        else if (!in_card(x, y)) close_menu();
        return 0;
    }
    case WM_SETCURSOR:
        // The game's pointer over the menu as well.
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

// The lines one under the other, as one text with line breaks.
std::wstring joined(const std::vector<std::wstring>& lines) {
    std::wstring out;
    for (std::size_t i = 0; i < lines.size(); ++i) out += (i ? L"\n" : L"") + lines[i];
    return out;
}

}  // namespace

void start(HWND frame, HWND game, const Hooks& hooks, bool korean) {
    g_frame = frame;
    g_game = game;
    g_hooks = hooks;
    g_korean = korean;
    GdiplusStartupInput input;
    GdiplusStartup(&g_gdiplus, &input, nullptr);
    g_notice = make_window(L"OpenDMTQNotice", notice_proc, true);
    g_button = make_window(L"OpenDMTQMenuButton", button_proc, false);
    g_menu = make_window(L"OpenDMTQMenu", menu_proc, false);
}

void notice(const std::string& text, bool live) {
    if (!g_notice) return;
    const std::wstring all = wide(text);
    const std::size_t cut = all.find(L'\n');
    std::wstring title = all.substr(0, cut), detail = cut == std::wstring::npos ? L"" : all.substr(cut + 1);
    // The card's size from its text: the mark, then the title over the detail.
    const auto family = face();
    Font title_font(family.get(), static_cast<REAL>(px(15)), FontStyleBold, UnitPixel);
    Font detail_font(family.get(), static_cast<REAL>(px(12.5f)), FontStyleRegular, UnitPixel);
    Font mark_font(family.get(), static_cast<REAL>(px(11.5f)), FontStyleBold, UnitPixel);
    const wchar_t* mark = live ? L"LIVE" : (g_korean ? L"방송 종료" : L"ENDED");
    const float pad = static_cast<float>(px(16)), gap = static_cast<float>(px(12)), dot = static_cast<float>(px(6));
    const float margin = static_cast<float>(px(10));
    RectF title_box, detail_box, mark_box;
    float mark_w = 0, room = 0;
    {
        Bitmap probe(1, 1, PixelFormat32bppPARGB);
        Graphics g(&probe);
        text_setup(g);
        g.MeasureString(mark, -1, &mark_font, PointF(0, 0), &mark_box);
        mark_w = mark_box.Width + dot + px(20);
        // The words' room: at most 520 pixels at 96 dpi, and within the game's area however small its window; a long
        // server name wraps there.
        const RECT a = area();
        const float beside = pad * 2 + mark_w + gap + margin * 2 + px(16);
        room = std::max(static_cast<float>(px(160)), std::min(static_cast<float>(px(520)), static_cast<float>(a.right - a.left) - beside));
        // Each line broken at its spaces within the room, then measured as the lines it became.
        title = joined(wrap_words(g, title, title_font, room));
        if (!detail.empty()) detail = joined(wrap_words(g, detail, detail_font, room));
        g.MeasureString(title.c_str(), -1, &title_font, PointF(0, 0), &title_box);
        if (!detail.empty()) g.MeasureString(detail.c_str(), -1, &detail_font, PointF(0, 0), &detail_box);
    }
    const float mark_h = static_cast<float>(px(22));
    const float text_w = std::max(title_box.Width, detail_box.Width);
    const float text_h = title_box.Height + (detail.empty() ? 0 : detail_box.Height + px(2));
    const int w = static_cast<int>(std::ceil(pad * 2 + mark_w + gap + text_w + margin * 2));
    const int h = static_cast<int>(std::ceil(pad * 2 + std::max(text_h, mark_h) + margin * 2));
    g_notice_canvas = std::make_unique<Canvas>(w, h);
    {
        auto bmp = g_notice_canvas->surface();
        Graphics g(bmp.get());
        text_setup(g);
        const RectF box(margin, margin, w - margin * 2, h - margin * 2);
        card(g, box, static_cast<float>(px(14)), kSurface);
        // The mark: a pill with a dot, red while live.
        const RectF pill(box.X + pad, box.Y + (box.Height - mark_h) / 2, mark_w, mark_h);
        GraphicsPath path;
        rounded(path, pill, mark_h / 2);
        SolidBrush pill_fill(live ? kLive : kEnded);
        g.FillPath(&pill_fill, &path);
        SolidBrush white(Color(255, 255, 255, 255));
        g.FillEllipse(&white, pill.X + px(9), pill.Y + (mark_h - dot) / 2, dot, dot);
        StringFormat middle;
        middle.SetLineAlignment(StringAlignmentCenter);
        g.DrawString(mark, -1, &mark_font, RectF(pill.X + px(9) + dot + px(5), pill.Y, mark_box.Width + px(4), mark_h), &middle, &white);
        // The title, and where to watch under it.
        const float tx = pill.X + mark_w + gap, ty = box.Y + (box.Height - text_h) / 2;
        SolidBrush text(kText), quiet(kQuiet);
        // Their lines as broken above: drawn as they were measured.
        g.DrawString(title.c_str(), -1, &title_font, PointF(tx, ty), &text);
        if (!detail.empty()) g.DrawString(detail.c_str(), -1, &detail_font, PointF(tx, ty + title_box.Height + px(2)), &quiet);
    }
    g_notice_shown = GetTickCount64();
    notice_frame();
    ShowWindow(g_notice, SW_SHOWNOACTIVATE);
    SetTimer(g_notice, kNoticeTimer, 15, nullptr);
}

void pointer_moved(int y, bool pressed) {
    // Not while the mouse plays (its button down), and only in the top quarter of the game: where a menu is looked for,
    // away from the notes.
    if (!g_button || menu_open() || pressed) return;
    const RECT a = area();
    if (y > (a.bottom - a.top) / 4) return;
    const bool shown = IsWindowVisible(g_button) && GetTickCount64() - g_moved < kButtonStayMs;
    g_moved = GetTickCount64();
    // Already there at full strength: only its time moves on, which its timer, due at the old time, finds then.
    if (shown) return;
    show_button();
}

bool menu_open() { return g_menu && (IsWindowVisible(g_menu) || g_menu_pending); }

// The menu on the screen, with the first row chosen, so that Enter at once is back to the game.
void show_menu() {
    g_menu_hover = 0;
    ShowWindow(g_button, SW_HIDE);
    draw_menu();
    // Where the pointer is now, in the menu's window (which covers the game's area).
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    g_menu_opened_at = POINT{p.x - a.left, p.y - a.top};
    ShowWindow(g_menu, SW_SHOWNOACTIVATE);
}

void open_menu() {
    if (!g_menu || menu_open()) return;
    // Over a minimised game it would show nowhere: the game comes back first.
    if (IsIconic(g_frame)) ShowWindow(g_frame, SW_RESTORE);
    show_menu();
    if (g_hooks.shown) g_hooks.shown(true);
}

void minimised(bool now) {
    if (!g_menu) return;
    if (now) {
        // Minimised mid-song: the game holds still as a phone's does when its owner leaves it, the menu waiting for the
        // game's return (shown now, it would stand alone on the desktop).
        if (menu_open()) return;
        g_menu_pending = true;
        if (g_hooks.shown) g_hooks.shown(true);
    } else if (g_menu_pending) {
        // Back: the menu, the game still held until the player chooses.
        g_menu_pending = false;
        show_menu();
    }
}

void close_menu() {
    if (!menu_open()) return;
    g_menu_pending = false;
    ShowWindow(g_menu, SW_HIDE);
    if (g_hooks.shown) g_hooks.shown(false);
}

bool menu_key(UINT vk) {
    if (!menu_open()) return false;
    const int n = static_cast<int>(items().size());
    if (vk == VK_UP || vk == VK_DOWN || vk == VK_TAB) {
        // Round the rows, as a list does.
        const int step = vk == VK_UP ? -1 : 1;
        g_menu_hover = g_menu_hover < 0 ? 0 : (g_menu_hover + step + n) % n;
        draw_menu();
    } else if (vk == VK_RETURN || vk == VK_SPACE) {
        choose(g_menu_hover < 0 ? 0 : g_menu_hover);
    } else if (vk == VK_ESCAPE) {
        close_menu();
    }
    // Every other key waits while the menu is open.
    return true;
}

void toggle_menu() {
    if (menu_open()) close_menu();
    else open_menu();
}

void place() {
    if (menu_open()) draw_menu();
    // The button's kept picture where the game's area went (drawn again only at another scale).
    if (g_button && IsWindowVisible(g_button)) show_button();
    if (g_notice_canvas) notice_frame();
}

// ---- the box for an error before the game: the launcher's dialog in a window of its own, as its dialogs.window()

namespace {

// The launcher's look (client/opendmtq_client/theme.py, art.py and dialogs.py), at 96 dpi.
const Color kField(255, 0x11, 0x15, 0x1a);   // the page behind (--field)
const Color kPanel(255, 0x1a, 0x1f, 0x25);   // the card (--deck)
const Color kChalk(255, 0xee, 0xf2, 0xf6);   // the question
const Color kAsh(255, 0xae, 0xb8, 0xc3);     // what it means
const Color kBad(255, 0xff, 0x5f, 0x72);     // the lamp of an error
const Color kCyan(255, 0x6f, 0xd6, 0xff);    // the keyboard's ring
const Color kInk(255, 0x0d, 0x1c, 0x04);     // the words on the lit button
constexpr float kBoxWidth = 480, kBoxPad = 28, kBoxCut = 16, kLampRoom = 18, kMargin = 44;
constexpr float kButtonHeight = 40, kButtonMin = 110, kButtonCut = 8;
// The site's shards at the page's edges (art.FACETS): opacity, then the points in a 1440 x 900 page.
struct Facet {
    float opacity;
    int n;
    PointF p[4];
};
const Facet kFacets[] = {
    {0.75f, 3, {{1440, 60}, {1330, 0}, {1440, 0}}},
    {0.62f, 4, {{1290, 70}, {1440, 250}, {1440, 420}, {1345, 300}}},
    {0.34f, 4, {{1345, 300}, {1440, 420}, {1440, 670}, {1400, 480}}},
    {0.72f, 3, {{0, 250}, {112, 470}, {0, 425}}},
    {0.30f, 4, {{0, 425}, {112, 470}, {176, 900}, {0, 900}}},
    {0.16f, 4, {{1400, 480}, {1440, 670}, {1440, 900}, {1344, 900}}},
};

struct ErrorBox {
    std::wstring message, detail, ok;
    float s = 1;                    // the system's scale: 1 at 96 dpi
    bool hover = false, pressed = false, done = false;
    RectF button;                   // where the button is in the window
    HWND window = nullptr;
    std::unique_ptr<Canvas> canvas;
};
ErrorBox* g_box = nullptr;

// Windows' scale for a window of its own, before any window is there to ask.
float system_scale() {
    using DpiOf = UINT(WINAPI*)();
    static auto dpi_of = reinterpret_cast<DpiOf>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForSystem"));
    if (dpi_of) return static_cast<float>(dpi_of()) / 96.0f;
    HDC dc = GetDC(nullptr);
    const float dpi = static_cast<float>(GetDeviceCaps(dc, LOGPIXELSY));
    ReleaseDC(nullptr, dc);
    return dpi / 96.0f;
}

// The outline of a card (the top-right corner cut) and of a button (the top-left and bottom-right cut).
void card_shape(GraphicsPath& path, RectF r, float cut) {
    const PointF p[] = {{r.X, r.Y}, {r.X + r.Width - cut, r.Y}, {r.X + r.Width, r.Y + cut},
                        {r.X + r.Width, r.Y + r.Height}, {r.X, r.Y + r.Height}};
    path.AddPolygon(p, 5);
}
void button_shape(GraphicsPath& path, RectF r, float cut) {
    const PointF p[] = {{r.X + cut, r.Y}, {r.X + r.Width, r.Y}, {r.X + r.Width, r.Y + r.Height - cut},
                        {r.X + r.Width - cut, r.Y + r.Height}, {r.X, r.Y + r.Height}, {r.X, r.Y + cut}};
    path.AddPolygon(p, 6);
}

// A colour between two (0: a, 1: b), at an alpha.
Color mixed(const Color& a, const Color& b, float k, BYTE alpha) {
    auto m = [k](BYTE x, BYTE y) { return static_cast<BYTE>(std::lround(x + (y - x) * k)); };
    return Color(alpha, m(a.GetR(), b.GetR()), m(a.GetG(), b.GetG()), m(a.GetB(), b.GetB()));
}

// The page behind, as the launcher's art.backdrop(): its field, a faint dot in every 6 px square, and the logo's lime
// shards at the left and right edges, each fading out downwards over 900 px.
void draw_backdrop(Graphics& g, float w, float h, float s) {
    SolidBrush field(kField);
    g.FillRectangle(&field, RectF(0, 0, w, h));
    const float step = std::max(4.0f, std::round(6 * s));
    SolidBrush dot(Color(11, 255, 255, 255));
    for (float y = step / 2; y < h; y += step)
        for (float x = step / 2; x < w; x += step) g.FillEllipse(&dot, x - s, y - s, 2 * s, 2 * s);
    const Color lime(255, 0x8c, 0xf2, 0x3d), white(255, 255, 255, 255), black(255, 0, 0, 0);
    const float span = 900 * s;
    // The colour down the shards: the lime a little whiter at the top, a little darker at the bottom.
    const Color top = mixed(lime, white, 0.12f, 255), bottom = mixed(lime, black, 0.30f, 255);
    for (const Facet& f : kFacets) {
        PointF at[4];
        for (int i = 0; i < f.n; ++i) at[i] = PointF(f.p[i].X / 1440.0f * w, f.p[i].Y / 900.0f * span);
        LinearGradientBrush fade(PointF(0, 0), PointF(0, span), Color(static_cast<BYTE>(255 * f.opacity), top.GetR(),
                                 top.GetG(), top.GetB()), Color(0, bottom.GetR(), bottom.GetG(), bottom.GetB()));
        g.FillPolygon(&fade, at, f.n);
    }
}

// The card's fonts: the question at 13 pt bold, the rest at 10 pt, the button's words bold (theme.Fonts).
struct BoxFonts {
    std::unique_ptr<FontFamily> family = face();
    Font title, body, bold;
    explicit BoxFonts(float s)
        : title(family.get(), 13.0f * 96 / 72 * s, FontStyleBold, UnitPixel),
          body(family.get(), 10.0f * 96 / 72 * s, FontStyleRegular, UnitPixel),
          bold(family.get(), 10.0f * 96 / 72 * s, FontStyleBold, UnitPixel) {}
};

// The window's picture: the page behind, the card on its shadow with the lamp, the question and what it means, and the
// button. The window is as tall as the card and its margins.
std::unique_ptr<Canvas> draw_box(ErrorBox& b) {
    const float s = b.s;
    BoxFonts f(s);
    const float card_w = kBoxWidth * s, pad = kBoxPad * s, lamp_room = kLampRoom * s;
    const float text_w = card_w - pad * 2 - lamp_room;
    // Measured first, on a picture of no size: the card is as tall as what it says.
    Bitmap scratch(1, 1, PixelFormat32bppPARGB);
    Graphics m(&scratch);
    text_setup(m);
    StringFormat wrap;
    RectF fit;
    m.MeasureString(b.message.c_str(), -1, &f.title, RectF(0, 0, text_w, 10000), &wrap, &fit);
    const float message_h = fit.Height;
    float detail_h = 0;
    if (!b.detail.empty()) {
        m.MeasureString(b.detail.c_str(), -1, &f.body, RectF(0, 0, text_w, 10000), &wrap, &fit);
        detail_h = fit.Height;
    }
    m.MeasureString(b.ok.c_str(), -1, &f.bold, PointF(0, 0), &fit);
    const float button_w = std::max(kButtonMin * s, fit.Width + 40 * s), button_h = kButtonHeight * s;
    const float card_h = pad + message_h + (detail_h > 0 ? 8 * s + detail_h : 0) + 24 * s + button_h + pad - 4 * s;
    const float margin = kMargin * s;
    auto canvas = std::make_unique<Canvas>(static_cast<int>(std::ceil(card_w + margin * 2)),
                                           static_cast<int>(std::ceil(card_h + margin * 2)));
    auto picture = canvas->surface();
    Graphics g(picture.get());
    text_setup(g);
    draw_backdrop(g, static_cast<float>(canvas->w), static_cast<float>(canvas->h), s);
    const RectF card(margin, margin, card_w, card_h);
    // The shadow: the card's outline a little lower and wider, darker towards the card, as the launcher's blur.
    for (int i = 8; i >= 1; --i) {
        GraphicsPath shadow;
        const float grow = 2.5f * s * static_cast<float>(i);
        card_shape(shadow, RectF(card.X - grow, card.Y - grow + 12 * s, card.Width + grow * 2, card.Height + grow * 2),
                   kBoxCut * s + grow);
        SolidBrush dark(Color(static_cast<BYTE>(30 - 3 * i), 0, 0, 0));
        g.FillPath(&dark, &shadow);
    }
    GraphicsPath outline;
    card_shape(outline, card, kBoxCut * s);
    SolidBrush panel(kPanel);
    g.FillPath(&panel, &outline);
    // A sheen at its head, fading out over 240 px, and a faint light along its top edge.
    {
        Region inside(&outline);
        g.SetClip(&inside);
        const float reach = std::min(240 * s, card_h);
        LinearGradientBrush sheen(PointF(0, card.Y - 1), PointF(0, card.Y + reach), Color(14, 255, 255, 255),
                                  Color(0, 255, 255, 255));
        g.FillRectangle(&sheen, RectF(card.X, card.Y, card_w, reach));
        g.ResetClip();
        Pen rim(Color(26, 255, 255, 255), std::max(1.0f, s));
        g.DrawLine(&rim, PointF(card.X, card.Y + 0.5f), PointF(card.X + card_w - kBoxCut * s, card.Y + 0.5f));
    }
    // The lamp: a 7 px dot of the error's red with its soft glow, beside the question's first line.
    {
        const float line = f.title.GetHeight(&g);
        const PointF c(card.X + pad + 4 * s + 3.5f * s, card.Y + pad + line / 2);
        GraphicsPath glow;
        const float reach = 10.5f * s;
        glow.AddEllipse(c.X - reach, c.Y - reach, reach * 2, reach * 2);
        PathGradientBrush soft(&glow);
        soft.SetCenterColor(Color(110, kBad.GetR(), kBad.GetG(), kBad.GetB()));
        Color edge(0, kBad.GetR(), kBad.GetG(), kBad.GetB());
        int one = 1;
        soft.SetSurroundColors(&edge, &one);
        g.FillPath(&soft, &glow);
        SolidBrush dot(kBad);
        g.FillEllipse(&dot, c.X - 3.5f * s, c.Y - 3.5f * s, 7 * s, 7 * s);
    }
    // The question in the bright text, what it means under it in the quiet one.
    SolidBrush chalk(kChalk), ash(kAsh), ink(kInk);
    const float text_x = card.X + pad + lamp_room;
    g.DrawString(b.message.c_str(), -1, &f.title, RectF(text_x, card.Y + pad, text_w, message_h + 4 * s), &wrap, &chalk);
    if (detail_h > 0) {
        g.DrawString(b.detail.c_str(), -1, &f.body, RectF(text_x, card.Y + pad + message_h + 8 * s, text_w,
                     detail_h + 4 * s), &wrap, &ash);
    }
    // The button at the card's foot on the right, lit in the logo's lime as the launcher's, with the keyboard's ring.
    b.button = RectF(card.X + card_w - pad - button_w, card.Y + card_h - (pad - 4 * s) - button_h, button_w, button_h);
    GraphicsPath face_path;
    button_shape(face_path, b.button, kButtonCut * s);
    LinearGradientBrush lit(PointF(0, b.button.Y - 1), PointF(0, b.button.Y + button_h + 1), Color(255, 0, 0, 0),
                            Color(255, 0, 0, 0));
    // The launcher's three colours down the button, for each state (art.BUTTON_LOOKS["home"]).
    const Color normal[] = {Color(255, 0xac, 0xf6, 0x73), Color(255, 0x8c, 0xf2, 0x3d), Color(255, 0x76, 0xcb, 0x33)};
    const Color hover[] = {Color(255, 0xbc, 0xf9, 0x8c), Color(255, 0x9d, 0xf5, 0x5a), Color(255, 0x82, 0xd8, 0x3c)};
    const Color pressed[] = {Color(255, 0x9e, 0xe6, 0x65), Color(255, 0x7f, 0xe2, 0x34), Color(255, 0x6b, 0xb9, 0x2e)};
    const REAL at[] = {0.0f, 0.5f, 1.0f};
    lit.SetInterpolationColors(b.pressed ? pressed : b.hover ? hover : normal, at, 3);
    g.FillPath(&lit, &face_path);
    {
        const float gap = 3 * s;
        GraphicsPath ring;
        button_shape(ring, RectF(b.button.X - gap, b.button.Y - gap, button_w + gap * 2, button_h + gap * 2),
                     (kButtonCut + 3) * s);
        Pen cyan(kCyan, std::max(2.0f, 2 * s));
        g.DrawPath(&cyan, &ring);
    }
    StringFormat centred;
    centred.SetAlignment(StringAlignmentCenter);
    centred.SetLineAlignment(StringAlignmentCenter);
    g.DrawString(b.ok.c_str(), -1, &f.bold, b.button, &centred, &ink);
    return canvas;
}

// What the box says, with a place to break a line after each separator of a path: a long path wraps between its
// folders, not inside a name.
std::wstring breakable(const std::string& text) {
    std::wstring out;
    for (wchar_t c : wide(text)) {
        out += c;
        if (c == L'\\' || c == L'/') out += L'\x200B';
    }
    return out;
}

void redraw(ErrorBox& b) {
    b.canvas = draw_box(b);
    InvalidateRect(b.window, nullptr, FALSE);
}

bool on_button(const ErrorBox& b, LPARAM l) {
    const float x = static_cast<float>(static_cast<short>(LOWORD(l)));
    const float y = static_cast<float>(static_cast<short>(HIWORD(l)));
    return b.button.Contains(x, y);
}

LRESULT CALLBACK box_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    ErrorBox* b = g_box;
    if (!b) return DefWindowProcW(h, msg, w, l);
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        if (b->canvas) BitBlt(dc, 0, 0, b->canvas->w, b->canvas->h, b->canvas->dc, 0, 0, SRCCOPY);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        // The picture covers all of it.
        return 1;
    case WM_MOUSEMOVE: {
        const bool over = on_button(*b, l);
        if (over != b->hover) {
            b->hover = over;
            redraw(*b);
        }
        TRACKMOUSEEVENT track{sizeof track, TME_LEAVE, h, 0};
        TrackMouseEvent(&track);
        return 0;
    }
    case WM_MOUSELEAVE:
        if (b->hover && !b->pressed) {
            b->hover = false;
            redraw(*b);
        }
        return 0;
    case WM_LBUTTONDOWN:
        if (on_button(*b, l)) {
            b->pressed = true;
            SetCapture(h);
            redraw(*b);
        }
        return 0;
    case WM_LBUTTONUP:
        if (b->pressed) {
            ReleaseCapture();
            b->pressed = false;
            // Let go on the button: answered; elsewhere: nothing.
            if (on_button(*b, l)) b->done = true;
            else redraw(*b);
        }
        return 0;
    case WM_KEYDOWN:
        if (w == VK_RETURN || w == VK_SPACE || w == VK_ESCAPE) b->done = true;
        return 0;
    case WM_CLOSE:
        b->done = true;
        return 0;
    default:
        return DefWindowProcW(h, msg, w, l);
    }
}

}  // namespace

void error_box(const std::string& message, const std::string& detail, bool korean) {
    // GDI+ for the picture, started here when the overlay has not (the game never came up).
    ULONG_PTR started = 0;
    if (!g_gdiplus) {
        GdiplusStartupInput input;
        GdiplusStartup(&started, &input, nullptr);
    }
    {
        g_korean = korean;
        ErrorBox b;
        b.message = wide(message);
        b.detail = breakable(detail);
        b.ok = korean ? L"\xD655\xC778" : L"OK";
        b.s = system_scale();
        g_box = &b;
        WNDCLASSEXW c{};
        c.cbSize = sizeof c;
        c.lpfnWndProc = box_proc;
        c.hInstance = GetModuleHandleW(nullptr);
        c.hCursor = LoadCursorA(nullptr, IDC_ARROW);
        // The player's own icon (player.rc), on the title bar, in the taskbar and Alt+Tab.
        c.hIcon = LoadIconW(c.hInstance, MAKEINTRESOURCEW(1));
        c.lpszClassName = L"OpenDMTQErrorBox";
        RegisterClassExW(&c);
        b.canvas = draw_box(b);
        // A window of Windows' own frame around the picture, in the middle of the screen's work area.
        const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
        RECT frame{0, 0, b.canvas->w, b.canvas->h};
        AdjustWindowRectEx(&frame, style, FALSE, 0);
        const int fw = frame.right - frame.left, fh = frame.bottom - frame.top;
        RECT work{};
        SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
        b.window = CreateWindowExW(0, c.lpszClassName, L"OpenDMTQ", style, work.left + (work.right - work.left - fw) / 2,
                                   work.top + (work.bottom - work.top - fh) / 2, fw, fh, nullptr, nullptr, c.hInstance,
                                   nullptr);
        if (b.window) {
            ShowWindow(b.window, SW_SHOW);
            SetForegroundWindow(b.window);
            SetFocus(b.window);
            MSG msg;
            while (!b.done && GetMessageW(&msg, nullptr, 0, 0) > 0) {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
            DestroyWindow(b.window);
        }
        g_box = nullptr;
    }
    if (started) GdiplusShutdown(started);
}

#ifdef OVERLAY_TEST_HOOKS
// For the overlay's own probe only (_work/winprobe): the notice's and the menu's pictures as PNGs, over the game's dark,
// where a locked or busy screen cannot be captured.
void test_save(const std::wstring& prefix) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    auto save = [&](Canvas* c, const wchar_t* name) {
        if (!c) return;
        Bitmap out(c->w, c->h, PixelFormat32bppARGB);
        Graphics g(&out);
        SolidBrush dark(Color(255, 22, 24, 26));
        g.FillRectangle(&dark, 0, 0, c->w, c->h);
        auto picture = c->surface();
        g.DrawImage(picture.get(), 0, 0, c->w, c->h);
        out.Save((prefix + name).c_str(), &png, nullptr);
    };
    save(g_notice_canvas.get(), L"notice.png");
    if (menu_open()) save(g_menu_canvas.get(), L"menu.png");
}

// The error box's window picture, at `scale`, in each of its states.
void test_save_error_box(const std::wstring& prefix, const std::string& message, const std::string& detail,
                         bool korean, float scale) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    g_korean = korean;
    ErrorBox b;
    b.message = wide(message);
    b.detail = breakable(detail);
    b.ok = korean ? L"\xD655\xC778" : L"OK";
    b.s = scale;
    const wchar_t* names[] = {L"box.png", L"box-hover.png", L"box-pressed.png"};
    for (int state = 0; state < 3; ++state) {
        b.hover = state == 1;
        b.pressed = state == 2;
        auto c = draw_box(b);
        auto picture = c->surface();
        Bitmap out(c->w, c->h, PixelFormat32bppARGB);
        Graphics g(&out);
        g.DrawImage(picture.get(), 0, 0, c->w, c->h);
        out.Save((prefix + names[state]).c_str(), &png, nullptr);
    }
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
