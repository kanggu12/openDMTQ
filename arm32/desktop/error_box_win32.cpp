// The player's box for an error before the game came up (own_folder.cpp's show_error): the launcher's own dialog in a
// window of its own, as its dialogs.window() draws one. The site's page behind, the cut card with the red lamp, the
// question and what it means, the lit button with the keyboard's ring; drawn with GDI+ into a picture of its own
// (canvas_win32.h) at Windows' scale, answered by its button, Enter, Space, Esc or the window's X. Where GDI+ or the
// window cannot be had, Windows' own message box says the same, so that no error goes unsaid.
#include "error_box_win32.h"

#include "canvas_win32.h"

#include <algorithm>
#include <cmath>
#include <memory>
#include <string>

namespace player::overlay {

namespace {

using namespace Gdiplus;

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
    bool korean = false;            // its face is Windows' own for Korean
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
    std::unique_ptr<FontFamily> family;
    Font title, body, bold;
    BoxFonts(float s, bool korean)
        : family(face(korean)),
          title(family.get(), 13.0f * 96 / 72 * s, FontStyleBold, UnitPixel),
          body(family.get(), 10.0f * 96 / 72 * s, FontStyleRegular, UnitPixel),
          bold(family.get(), 10.0f * 96 / 72 * s, FontStyleBold, UnitPixel) {}
};

// The window's picture: the page behind, the card on its shadow with the lamp, the question and what it means, and the
// button. The window is as tall as the card and its margins. Null when Windows could not make a picture of that size.
std::unique_ptr<Canvas> draw_box(ErrorBox& b) {
    const float s = b.s;
    BoxFonts f(s, b.korean);
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
    // No pixels of its own (Windows refused the DIB): nothing to draw into, and nothing to show.
    if (!canvas->bits) return nullptr;
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

// The launcher's dialog in a window of its own, until the player answers it; false when it could not be drawn or shown
// (no picture, no window), and nothing is on the screen then.
bool show_box(const std::string& message, const std::string& detail, bool korean) {
    ErrorBox b;
    b.korean = korean;
    b.message = wide(message);
    b.detail = breakable(detail);
    b.ok = korean ? L"\xD655\xC778" : L"OK";
    b.s = system_scale();
    b.canvas = draw_box(b);
    if (!b.canvas) return false;
    WNDCLASSEXW c{};
    c.cbSize = sizeof c;
    c.lpfnWndProc = box_proc;
    c.hInstance = GetModuleHandleW(nullptr);
    c.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    // The player's own icon (player.rc), on the title bar, in the taskbar and Alt+Tab.
    c.hIcon = LoadIconW(c.hInstance, MAKEINTRESOURCEW(1));
    c.lpszClassName = L"OpenDMTQErrorBox";
    RegisterClassExW(&c);
    // A window of Windows' own frame around the picture, in the middle of the screen's work area.
    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    RECT frame{0, 0, b.canvas->w, b.canvas->h};
    AdjustWindowRectEx(&frame, style, FALSE, 0);
    const int fw = frame.right - frame.left, fh = frame.bottom - frame.top;
    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    // The window's procedure finds the box here from its first message on.
    g_box = &b;
    b.window = CreateWindowExW(0, c.lpszClassName, L"OpenDMTQ", style, work.left + (work.right - work.left - fw) / 2,
                               work.top + (work.bottom - work.top - fh) / 2, fw, fh, nullptr, nullptr, c.hInstance, nullptr);
    if (!b.window) {
        g_box = nullptr;
        return false;
    }
    ShowWindow(b.window, SW_SHOW);
    SetForegroundWindow(b.window);
    SetFocus(b.window);
    // Its own loop until it is answered (or the program is told to quit).
    MSG msg;
    while (!b.done && GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    DestroyWindow(b.window);
    g_box = nullptr;
    return true;
}

// Windows' own message box with the same words: where the launcher's dialog cannot be had, the error is still said.
void plain_box(const std::string& message, const std::string& detail) {
    const std::wstring text = wide(detail.empty() ? message : message + "\n\n" + detail);
    MessageBoxW(nullptr, text.c_str(), L"OpenDMTQ", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
}

}  // namespace

void error_box(const std::string& message, const std::string& detail, bool korean) {
    // GDI+ for the picture while the box is up: a start of its own, counted beside the overlay's if that started too,
    // and ended after it.
    ULONG_PTR token = 0;
    GdiplusStartupInput input;
    const bool gdiplus = GdiplusStartup(&token, &input, nullptr) == Ok;
    const bool shown = gdiplus && show_box(message, detail, korean);
    if (gdiplus) GdiplusShutdown(token);
    // Without GDI+, a picture or the window: Windows' own box.
    if (!shown) plain_box(message, detail);
}

#ifdef OVERLAY_TEST_HOOKS
// The box's window picture at `scale` in each of its states, made with no window: for its probe only (_work/winprobe).
void test_save_error_box(const std::wstring& prefix, const std::string& message, const std::string& detail,
                         bool korean, float scale) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    ErrorBox b;
    b.korean = korean;
    b.message = wide(message);
    b.detail = breakable(detail);
    b.ok = korean ? L"\xD655\xC778" : L"OK";
    b.s = scale;
    const wchar_t* names[] = {L"box.png", L"box-hover.png", L"box-pressed.png"};
    for (int state = 0; state < 3; ++state) {
        b.hover = state == 1;
        b.pressed = state == 2;
        auto c = draw_box(b);
        // No picture to save where Windows could not make one.
        if (!c) continue;
        auto picture = c->surface();
        Bitmap out(c->w, c->h, PixelFormat32bppARGB);
        Graphics g(&out);
        g.DrawImage(picture.get(), 0, 0, c->w, c->h);
        out.Save((prefix + names[state]).c_str(), &png, nullptr);
    }
}
#endif

}  // namespace player::overlay
