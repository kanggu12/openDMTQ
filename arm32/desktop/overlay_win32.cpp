// What the player for Windows draws over the game itself (window_win32.cpp places and feeds it), as frosted glass in the
// game's own shapes and colours: the game shows through each piece, blurred, under a charcoal tint, with a light edge
// and the game's bevel (a line of light along the top, of shade along the foot) and a soft shadow under it
// (overlay_glass.h makes the glass); its corners small as the game's, its green line along the bar's and the notice's
// foot. The game's lime marks what is lit or chosen, its green button the way on, red what ends or what is live. Each
// piece is a layered window of its own above the game's window, drawn into a premultiplied 32-bit picture and shown with
// UpdateLayeredWindow, so its edges are smooth and its fades cost the game nothing. The game's frame behind a piece
// comes from the render thread (glass_capture.h), read at a quarter of its size while a piece is up, at most 20 times a
// second; a piece is drawn again only when what is behind it changed. Before a frame has been read, a piece is its bare
// tint, solid enough to read.
//
// - The bar: a PC has no phone's buttons around the game, so a bar of glass across the top of the game's area shows when
//   the pointer rests at the very top edge with its button up, or when a finger is drawn down from the top edge.
//   "OPEN DMTQ" on its left in the launcher's wordmark face; on its right two chips like the game's OFF chips, full
//   screen (or back to a window) and an X that quits after asking. Under the pointer the full screen chip lights with a
//   lime edge and the X turns red, as Windows' own close does; held, a chip is pressed in. It stays while the pointer is
//   on it and fades soon after it leaves, so it never sits on the game's own controls at the top while they are used.
//   No key opens it.
// - The question before quitting: the bar's X and the window's own close ask it. The game dims and blurs behind a card of
//   glass with the question, the game's green line under it, a thin X, Keep playing as the game's green button and Quit
//   the game in the grey of its tabs, red under the pointer; the keys' choice marked as the game marks a chosen card. The
//   game holds still meanwhile, so a click by mistake mid-song loses nothing. Alt+F4 does nothing.
// - The notice: the server's two-line notice about a broadcast (a title, then where to watch), as a glass card that
//   slides down at the top of the game, stays for a few seconds and fades. A red LIVE tag with a slanted end, as the
//   game's tags, while broadcasting, a grey one when the broadcast has ended.
// - The cursor: a dart in the logo's chrome and lime, all lime while the mouse's finger is down on the game.
// - The frame counter: when the PC's settings ask for it, a small glass box like the game's Q and MAX box in the corner
//   the player picks, 8 pixels in at 720 lines: FPS in the game's lime, the frames a second in white and the mean frame
//   time under them, over the last half second, drawn twice a second from the count of frames shown that the player
//   keeps anyway (frames.cpp). It lets clicks through, and stays under the question's dim while that is up.
#include "overlay_win32.h"

// GDI+ and the picture it draws into, which the error box before the game draws with too (error_box_win32.cpp).
#include "canvas_win32.h"
// The game's frame behind the glass, read on the render thread; the glass and the faces.
#include "glass_capture.h"
#include "overlay_glass.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
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

#ifdef OVERLAY_TEST_HOOKS
// The probe's stand-in for Windows' scale (0: Windows' own), so that 150 % can be drawn on a PC at 100 %.
float g_test_dpi = 0;
// The probe's places as with the bar up (top_room).
bool g_test_bar_up = false;
// The probe's pictures without their words: the glass under the words alone, for their contrast.
bool g_test_no_words = false;
// The probe draws only: no window is ever shown or moved.
bool g_test_quiet = false;
// Where the words of the piece being drawn went and in what colour, for the probe's measure of their contrast.
struct TestText {
    Gdiplus::RectF box;
    Gdiplus::Color colour;
};
std::vector<TestText>* g_test_texts = nullptr;
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

// The game's area's size.
int area_w() {
    const RECT a = area();
    return std::max(1, static_cast<int>(a.right - a.left));
}
int area_h() {
    const RECT a = area();
    return std::max(1, static_cast<int>(a.bottom - a.top));
}

// The overlay's scale: the game's, which lays itself out for 720 lines and grows with its area (1.5 at 1080 lines, 3 at
// 4K), or Windows' own when that is larger (a small window on a display at 200 %), so that the bar, the question and the
// notice keep their size beside the game's own dialogs and buttons.
// A cap on the scale while one piece is laid out and drawn (0: none): the question's card, which keeps within the
// game's area (AskScale below).
float g_scale_cap = 0;

float scale() {
    const float s = std::max(dpi_scale(), static_cast<float>(area_h()) / 720.0f);
    return g_scale_cap > 0 ? std::min(s, g_scale_cap) : s;
}

// The question's card at 720 lines: its width and its height.
constexpr float kCardWidth = 520, kCardHeight = 228;

// The question's card at most three quarters of the game's area wide and nine tenths of it high, everything in it scaled
// with it: a small window on a display at 150 % or 200 % gets a card in proportion to the game instead of one across its
// whole width. Held while the card is laid out or drawn.
struct AskScale {
    float before;
    AskScale() : before(g_scale_cap) {
        g_scale_cap = std::min(0.75f * static_cast<float>(area_w()) / kCardWidth, 0.9f * static_cast<float>(area_h()) / kCardHeight);
    }
    ~AskScale() { g_scale_cap = before; }
    AskScale(const AskScale&) = delete;
    AskScale& operator=(const AskScale&) = delete;
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

// ---- words

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

// The probe's note of words drawn (or that would be), opaque ones only: a faint one under them is no words of its own.
void note_words(RectF box, const Color& colour) {
#ifdef OVERLAY_TEST_HOOKS
    if (g_test_texts && colour.GetA() == 255) g_test_texts->push_back(TestText{box, colour});
#else
    (void)box;
    (void)colour;
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
    note_words(RectF(box.X + (box.Width - tw) / 2, box.Y + (box.Height - size.Height) / 2, tw, size.Height), colour);
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

// ---- the glass's pieces

// A piece of glass on the screen: its window, its look, the picture shown and where, and what that picture was made from
// (its look, the frame behind and its place), so that it is made again only when one of them changed.
struct Pane {
    HWND window = nullptr;
    Look look;
    // A number that changes with every new look.
    int look_serial = 0;
    std::unique_ptr<Canvas> picture;
    // The window's place in the game's window, and its opacity as a whole.
    int x = 0, y = 0;
    BYTE alpha = 255;
    // The frame behind it, blurred, for the place it was made for, and the hash of what it was made from.
    Backdrop backdrop;
    std::uint64_t backdrop_from = 0;
    bool have_backdrop = false;
    // What the picture shows: its look, its frame's hash (0: the bare tint) and its place.
    int drawn_serial = -1;
    std::uint64_t drawn_hash = 1;
    int drawn_x = -1, drawn_y = -1;
};

// What the render thread read last (none yet: an empty list), and how many reads there have been by then (glass::take());
// when it came.
std::shared_ptr<const std::vector<glass::Shot>> g_shots = std::make_shared<const std::vector<glass::Shot>>();
unsigned g_shots_seen = 0;
UINT64 g_shots_at = 0;

// The blur's reach around a piece, which the reads take in as well: three sigmas.
int blur_reach() { return px(kGlassBlur * 3); }

// The frame behind a pane's window as it is now, blurred and tinted toward saturation: made again only when what it is
// made from changed. False when no read holds it (the bare tint then).
bool pane_backdrop(Pane& p) {
    Backdrop raw;
    if (!backdrop_from(*g_shots, glass::Rect{p.x, p.y, p.look.w, p.look.h}, blur_reach(), raw)) {
        p.have_backdrop = false;
        return false;
    }
    if (!p.have_backdrop || raw.hash != p.backdrop_from) {
        p.backdrop_from = raw.hash;
        soften(raw, fpx(kGlassBlur), kGlassSaturation, 0);
        p.backdrop = std::move(raw);
        p.have_backdrop = true;
    }
    return true;
}

// The pane's picture as its look, the frame behind and its place make it now; true when it changed.
bool pane_draw(Pane& p) {
    const bool behind = pane_backdrop(p);
    const std::uint64_t hash = behind ? p.backdrop_from : 0;
    if (p.picture && p.drawn_serial == p.look_serial && p.drawn_hash == hash && p.drawn_x == p.x && p.drawn_y == p.y && p.picture->w == p.look.w &&
        p.picture->h == p.look.h) {
        return false;
    }
    if (!p.picture || p.picture->w != p.look.w || p.picture->h != p.look.h) p.picture = std::make_unique<Canvas>(std::max(1, p.look.w), std::max(1, p.look.h));
    if (!p.picture->bits) return false;
    // From nothing: a piece alone over the game.
    std::memset(p.picture->bits, 0, static_cast<std::size_t>(p.picture->w) * static_cast<std::size_t>(p.picture->h) * 4);
    compose(*p.picture, 0, 0, p.look, behind ? &p.backdrop : nullptr, p.x, p.y);
    p.drawn_serial = p.look_serial;
    p.drawn_hash = hash;
    p.drawn_x = p.x;
    p.drawn_y = p.y;
    return true;
}

// The pane's picture on the screen at its place and opacity.
void pane_show(Pane& p) {
    if (!p.picture || !showing()) return;
    const RECT a = area();
    p.picture->show(p.window, a.left + p.x, a.top + p.y, p.alpha);
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
// Its green buttons (RANKINGS, PLAY AGAIN): a light top edge, a gradient through a darker middle, a dark foot edge,
// corners of about 4, white bold words.
const Color kGreenEdgeTop(255, 0x6E, 0xC1, 0x30), kGreenEdgeFoot(255, 0x0C, 0x4A, 0x01);
// Its inactive tabs: a light top edge over a grey gradient.
const Color kTabEdgeTop(255, 0x8D, 0x8D, 0x8D), kTabTop(255, 0x5F, 0x60, 0x60), kTabFoot(255, 0x38, 0x3A, 0x3C);
// Its OFF chips: a dark grey the picture behind tints.
const Color kChip(220, 0x2B, 0x2B, 0x2B);
// The red of a close, as Windows' own turns, light to deep; its light top edge.
const Color kRedTop(255, 0xC4, 0x2B, 0x1C), kRedFoot(255, 0x9E, 0x1F, 0x14), kRedEdgeTop(255, 0xE0, 0x5A, 0x4C);
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

// The keys' choice on a button, as the game marks its chosen card: a lime border on the button's edge and a soft lime
// glow around it (the glow goes under what the canvas holds: call it before drawing the button).
void chosen_glow(Canvas& c, Graphics& g, RectF r, float radius) {
    GraphicsPath path;
    rounded(path, r, radius);
    // What GDI+ has drawn so far is in the picture before the glow goes under it.
    g.Flush(FlushIntentionSync);
    glow(c, r, fpx(5), 0, 0, Color(150, tone::kLime.GetR(), tone::kLime.GetG(), tone::kLime.GetB()), [&](Graphics& m) {
        Pen ring(Color(255, 255, 255, 255), fpx(3));
        m.DrawPath(&ring, &path);
    });
}
void chosen_border(Graphics& g, RectF r, float radius) {
    const float line = std::max(2.0f, fpx(2));
    GraphicsPath path;
    // On the button's outermost pixels: half the border's width in.
    rounded(path, RectF(r.X + line / 2, r.Y + line / 2, r.Width - line, r.Height - line), std::max(0.0f, radius - line / 2));
    Pen lime(tone::kLime, line);
    g.DrawPath(&lime, &path);
}

// A button's face: a vertical gradient through the stops given (top to foot), its light top edge (none pressed in)
// and its dark foot edge, as the game's buttons are made.
void button_face(Graphics& g, RectF r, float radius, const Color* colours, const REAL* at, int n, const Color* edge_top, const Color& edge_foot) {
    GraphicsPath path;
    rounded(path, r, radius);
    // A pixel beyond both ends, so that the gradient's ends do not wrap over the first and last rows.
    LinearGradientBrush fill(PointF(0, r.Y - 1), PointF(0, r.Y + r.Height + 1), colours[0], colours[n - 1]);
    fill.SetInterpolationColors(colours, at, n);
    g.FillPath(&fill, &path);
    const float line = std::max(1.0f, fpx(1));
    const float x0 = r.X + std::max(radius * 0.6f, line), x1 = r.X + r.Width - std::max(radius * 0.6f, line);
    if (edge_top) {
        Pen top(*edge_top, line);
        g.DrawLine(&top, x0, r.Y + line / 2, x1, r.Y + line / 2);
    }
    Pen foot(edge_foot, line);
    g.DrawLine(&foot, x0, r.Y + r.Height - line / 2, x1, r.Y + r.Height - line / 2);
}

// The game's green button (Keep playing): its light top edge, its gradient (#44A205 at the top, then darker than the
// game's #3B8C04 where the white words sit, so that they keep 4.5:1: #348104 is 4.9:1), its dark foot edge, white
// bold words. A touch lighter under the pointer (4.6:1); pressed in, darker, without its top edge, the words a pixel
// lower (the caller's).
void green_button(Canvas& c, Graphics& g, RectF r, bool lit, bool in, bool chosen) {
    const float radius = fpx(4);
    if (chosen) chosen_glow(c, g, r, radius);
    const REAL at[] = {0.0f, 0.3f, 0.7f, 1.0f};
    if (in) {
        const Color colours[] = {Color(255, 0x27, 0x66, 0x03), Color(255, 0x2A, 0x6D, 0x03), Color(255, 0x25, 0x62, 0x02), Color(255, 0x1F, 0x56, 0x00)};
        button_face(g, r, radius, colours, at, 4, nullptr, game::kGreenEdgeFoot);
    } else if (lit) {
        const Color colours[] = {Color(255, 0x4D, 0xB0, 0x0A), Color(255, 0x36, 0x85, 0x05), Color(255, 0x30, 0x78, 0x05), Color(255, 0x27, 0x66, 0x03)};
        button_face(g, r, radius, colours, at, 4, &game::kGreenEdgeTop, game::kGreenEdgeFoot);
    } else {
        const Color colours[] = {Color(255, 0x44, 0xA2, 0x05), Color(255, 0x34, 0x81, 0x04), Color(255, 0x2E, 0x74, 0x04), Color(255, 0x24, 0x60, 0x00)};
        button_face(g, r, radius, colours, at, 4, &game::kGreenEdgeTop, game::kGreenEdgeFoot);
    }
    if (chosen) chosen_border(g, r, radius);
}

// The game's inactive tab as a button (Quit the game): its light top edge over its grey gradient at 85 %, the glass
// showing faintly through; under the pointer red, as a close turns; pressed in, darker, without its top edge.
void tab_button(Canvas& c, Graphics& g, RectF r, bool lit, bool in, bool chosen) {
    const float radius = fpx(4);
    if (chosen) chosen_glow(c, g, r, radius);
    const REAL at[] = {0.0f, 1.0f};
    if (lit) {
        const Color colours[] = {in ? Color(255, 0xA8, 0x24, 0x18) : game::kRedTop, in ? Color(255, 0x86, 0x1A, 0x11) : game::kRedFoot};
        button_face(g, r, radius, colours, at, 2, in ? nullptr : &game::kRedEdgeTop, Color(200, 0x5A, 0x10, 0x0A));
    } else {
        const Color colours[] = {in ? Color(217, 0x48, 0x49, 0x4A) : Color(217, game::kTabTop.GetR(), game::kTabTop.GetG(), game::kTabTop.GetB()),
                                 in ? Color(217, 0x2C, 0x2E, 0x30) : Color(217, game::kTabFoot.GetR(), game::kTabFoot.GetG(), game::kTabFoot.GetB())};
        button_face(g, r, radius, colours, at, 2, in ? nullptr : &game::kTabEdgeTop, Color(160, 0x08, 0x08, 0x08));
    }
    if (chosen) chosen_border(g, r, radius);
}

// The game's OFF chip as the bar's chip: a dark grey the glass behind tints, corners of 4, the game's bevel; red under
// the pointer for the X; a pixel lime border for the full screen chip under the pointer; pressed in, darker, its bevel
// the other way round.
void off_chip(Graphics& g, RectF r, bool in, bool red, bool lit) {
    const float radius = fpx(4);
    GraphicsPath path;
    rounded(path, r, radius);
    if (red) {
        const Color colours[] = {in ? Color(255, 0xA8, 0x24, 0x18) : game::kRedTop, in ? Color(255, 0x86, 0x1A, 0x11) : game::kRedFoot};
        const REAL at[] = {0.0f, 1.0f};
        LinearGradientBrush fill(PointF(0, r.Y - 1), PointF(0, r.Y + r.Height + 1), colours[0], colours[1]);
        fill.SetInterpolationColors(colours, at, 2);
        g.FillPath(&fill, &path);
    } else {
        SolidBrush fill(in ? Color(235, 0x1E, 0x1F, 0x20) : game::kChip);
        g.FillPath(&fill, &path);
    }
    // Raised: light along the top, shade along the foot; pressed in, the other way round.
    const float line = std::max(1.0f, fpx(1));
    const float x0 = r.X + std::max(radius, line), x1 = r.X + r.Width - std::max(radius, line);
    Pen light(Color(in ? 20 : 56, 255, 255, 255), line), dark(Color(in ? 110 : 90, 0, 0, 0), line);
    g.DrawLine(in ? &dark : &light, x0, r.Y + line / 2, x1, r.Y + line / 2);
    g.DrawLine(in ? &light : &dark, x0, r.Y + r.Height - line / 2, x1, r.Y + r.Height - line / 2);
    if (lit) {
        // The full screen chip under the pointer: a pixel of the game's lime around it.
        GraphicsPath ring;
        rounded(ring, RectF(r.X + line / 2, r.Y + line / 2, r.Width - line, r.Height - line), std::max(0.0f, radius - line / 2));
        Pen lime(tone::kLime, line);
        g.DrawPath(&lime, &ring);
    }
}

// ---- the notice

Pane g_notice;
std::string g_notice_text;
bool g_notice_live = false;
bool g_notice_up = false;
UINT64 g_notice_shown = 0;  // GetTickCount64 when it came
constexpr UINT_PTR kNoticeTimer = 1;
// Sliding in (12 pixels down, fading in, easing out), staying, fading out.
constexpr UINT64 kSlideMs = 220, kStayMs = 6000, kFadeMs = 300;
constexpr float kSlide = 12;
// Where the notice's look was made for (the room the bar takes above it, the game's area's size), to make it again for
// another.
int g_notice_room = -1, g_notice_area_w = 0, g_notice_area_h = 0;
float g_notice_scale = 0;

// The room the bar takes at the top of the game's area while it is up (0 while it is not): what sits at the top moves
// under it rather than being covered (bar_frame and hide_bar move them).
int top_room();

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

Pane g_fps;
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
// What its look was made for: the numbers, the scale, its place and its window.
int g_fps_drawn = -2;
float g_fps_drawn_ms = -1, g_fps_drawn_scale = 0;
RECT g_fps_drawn_window{};

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

// The right edge of the game's pause button in a song, at 720 lines: the button spans 13 to 72 from the left (measured
// on the game's frames), at the game's own scale (its height over 720), whatever Windows' scale.
constexpr float kPauseRight = 73;

// The counter's glass's top left: its corner of the game's area, 8 pixels in at 720 lines; top left, 8 pixels right of
// the game's pause button, so that it covers nothing a song uses; in a top corner, under the bar while that is up.
POINT fps_place(int chip_w, int chip_h) {
    const int in = px(8);
    const bool right = g_fps_corner == 2 || g_fps_corner == 4, bottom = g_fps_corner == 3 || g_fps_corner == 4;
    const float game = static_cast<float>(area_h()) / 720.0f;
    const int left = g_fps_corner == 1 ? static_cast<int>(std::lround(kPauseRight * game)) + in : in;
    return POINT{right ? area_w() - in - chip_w : left, bottom ? area_h() - in - chip_h : in + top_room()};
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

// The counter's look for `fps` frames a second and `ms` a frame (fps below 0: not known yet, dashes), in its window `win`
// with its glass at `chip` (both in the game's window): the game's Q and MAX box in glass, its green-black over the
// frame, a pixel of lime around it, the label in lime, the number white and bold, the time grey.
void fps_look(int fps, float ms, RECT win, RECT chip) {
    const FpsMetrics m = fps_metrics();
    Look& look = g_fps.look;
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
    // The number, right-aligned digit by digit in cells as wide as the widest digit; before the first count, a dash as
    // wide as two of them.
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
    // The mean frame time under the number, grey, right-aligned; no frame in the half second (the game held still): no
    // time between frames either.
    wchar_t time[32];
    if (fps <= 0) std::swprintf(time, 32, L"-- ms");
    else std::swprintf(time, 32, L"%.1f ms", static_cast<double>(ms));
    const float time_w = measure(time, *time_font).Width;
    say(*g, time, *time_font, tone::kSecondary, PointF(right - time_w, top + m.number_h * 0.86f));
    // The words' zone: the glass's inside, as dark as the quiet grey needs.
    look.zones = {Look::Zone{glass.X + m.pad_x / 2, glass.Y + m.pad_y / 2, glass.X + glass.Width - m.pad_x / 2, glass.Y + glass.Height - m.pad_y / 2,
                             kUnderSecondary}};
    look.feather = fpx(6);
    ++g_fps.look_serial;
}

// The counter where its corner is now, drawn again only when its numbers, its scale or its place changed: a move of
// the window counts nothing.
void fps_place_now() {
    if (!g_fps.window || !g_fps_corner) return;
    const FpsMetrics m = fps_metrics();
    const POINT at = fps_place(static_cast<int>(m.w), static_cast<int>(m.h));
    const RECT chip{at.x, at.y, at.x + static_cast<LONG>(m.w), at.y + static_cast<LONG>(m.h)};
    const RECT win = window_around(chip.left, chip.top, static_cast<int>(m.w), static_cast<int>(m.h));
    if (g_fps_drawn != g_fps_shown || g_fps_drawn_ms != g_fps_shown_ms || g_fps_drawn_scale != scale() || !EqualRect(&g_fps_drawn_window, &win)) {
        fps_look(g_fps_shown, g_fps_shown_ms, win, chip);
        g_fps_drawn = g_fps_shown;
        g_fps_drawn_ms = g_fps_shown_ms;
        g_fps_drawn_scale = scale();
        g_fps_drawn_window = win;
    }
    g_fps.x = win.left;
    g_fps.y = win.top;
    g_fps.alpha = 255;
    pane_draw(g_fps);
    pane_show(g_fps);
}

// A look at the count, twice a second: the frames since the last look over the time between their own last frames,
// drawn again when what it shows changed.
void fps_frame() {
    if (!g_fps.window || !g_fps_frames) return;
    const FrameCount now = g_fps_frames();
    int fps = g_fps_shown;
    float ms = g_fps_shown_ms;
    rate(g_fps_last, now, fps, ms);
    // Held still (no frame since the last look): the next look starts afresh from its own count, so that the time the
    // game stood still is not taken for one long frame once it goes on.
    g_fps_last = fps == 0 ? FrameCount{} : now;
    if (fps != g_fps_shown || std::fabs(ms - g_fps_shown_ms) >= 0.05f) {
        g_fps_shown = fps;
        g_fps_shown_ms = ms;
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

Pane g_bar;
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
// The pointer waits at the top edge: the bar may come, and the frame behind it is read meanwhile, so that it comes as
// glass rather than its bare tint.
bool g_bar_coming = false;
// What its look was made for: its width, the scale, the chip under the pointer, the one held, full screen or not.
int g_bar_look_w = 0, g_bar_look_hover = -2, g_bar_look_pressed = -2;
float g_bar_look_scale = 0;
bool g_bar_look_full = false;
bool g_bar_up = false;

// The bar's height, the chips' size, the gap between them and their room from the bar's right end, at this scale. 74
// at 720 lines: the game's own X at the top right of its song and music screens reaches row 70 (its soft edge, measured
// on the game's frames), and the bar covers it whole with 4 to spare.
int bar_height() { return px(74); }
int chip_size() { return px(40); }
int chip_gap() { return px(10); }
int chip_margin() { return px(16); }

int top_room() {
#ifdef OVERLAY_TEST_HOOKS
    // The probe's places with the bar up, its windows being hidden.
    if (g_test_bar_up) return bar_height();
#endif
    return g_bar_up ? bar_height() : 0;
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
    for (int which : {kQuitChip, kScreenChip}) {
        if (chip_rect(which, area_w()).Contains(static_cast<REAL>(x), static_cast<REAL>(y))) return which;
    }
    return kNone;
}

// Whether the frame is in full screen, as the window says.
bool full_screen() { return g_hooks.fullscreen && g_hooks.fullscreen(); }

// The full screen chip's icon centred at (cx, cy): four corner brackets, their corners out (to full screen) or in (back
// to a window, when `full`).
void screen_icon(Graphics& g, Pen& line, float cx, float cy, bool full) {
    // The brackets' reach from the centre and the length of each arm.
    const float outer = fpx(8), inner = fpx(3), arm = fpx(4.5f);
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

// The bar's name in the launcher's wordmark face, "OPEN DMTQ" spaced out as the launcher's header spaces its OPEN (set
// plainly as "OpenDMTQ", the wide face's small letters read heavier and cramped); where it went, for its words' zone.
RectF bar_name(Graphics& g, float h) {
    const std::wstring name = L"OPEN DMTQ";
    // 0.2 em after each letter.
    const float size = fpx(15);
    const float spacing = size * 0.2f;
    auto f = wide_font(size);
    const float line = measure(L"O", *f).Height;
    const float x0 = fpx(22), y = (h - line) / 2;
    float x = x0;
    for (std::size_t i = 0; i < name.size(); ++i) {
        const std::wstring letter(1, name[i]);
        say(g, letter, *f, tone::kPrimary, PointF(x, y));
        x += measure(letter, *f).Width + (i + 1 < name.size() ? spacing : 0.0f);
    }
    return RectF(x0, y, x - x0, line);
}

// The bar's look as it is now, made again only when it changed.
void bar_look() {
    const int w = area_w();
    const float now_scale = scale();
    const bool full = full_screen();
    if (g_bar.look.fore && g_bar_look_w == w && g_bar_look_hover == g_bar_hover && g_bar_look_pressed == g_bar_pressed && g_bar_look_scale == now_scale &&
        g_bar_look_full == full) {
        return;
    }
    const bool resized = g_bar_look_w != w || g_bar_look_scale != now_scale;
    g_bar_look_w = w;
    g_bar_look_hover = g_bar_hover;
    g_bar_look_pressed = g_bar_pressed;
    g_bar_look_scale = now_scale;
    g_bar_look_full = full;
    Look& look = g_bar.look;
    const int h = bar_height();
    const int win_h = h + px(kRoomBottom);
    // Glass across the game's whole width, square, from its very top: its shape goes past the window's sides and top,
    // so that its shadow falls evenly under it. Made again only for a new width or scale.
    if (resized || look.w != w || look.h != win_h) pane_shape(look, w, win_h, RectF(-1000, -1000, static_cast<REAL>(w + 2000), static_cast<REAL>(h + 1000)), 0, true);
    look.top = 0;
    look.height = static_cast<float>(h);
    look.tint = kTintPiece;
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
    // The two chips as the game's OFF chips: the full screen chip with a lime edge under the pointer, the X red; pressed
    // in while held there; a white glyph of 2 pixels (lime on the lit full screen chip), a pixel lower pressed in.
    for (int which : {kQuitChip, kScreenChip}) {
        const RectF r = chip_rect(which, w);
        const bool quit = which == kQuitChip;
        const bool hover = which == g_bar_hover, in = hover && which == g_bar_pressed;
        off_chip(*g, r, in, quit && hover, !quit && hover);
        const float down = in ? std::max(1.0f, fpx(1)) : 0.0f;
        Pen line_pen(!quit && hover ? tone::kLime : Color(255, 255, 255, 255), fpx(2));
        line_pen.SetLineJoin(LineJoinMiter);
        const float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2 + down;
        if (quit) {
            line_pen.SetStartCap(LineCapRound);
            line_pen.SetEndCap(LineCapRound);
            cross(*g, line_pen, cx, cy, fpx(6.5f));
        } else {
            screen_icon(*g, line_pen, cx, cy, full);
        }
    }
    // The name's zone: the tint deepens there as much as the frame behind needs for it.
    look.zones = {Look::Zone{name.X - fpx(6), name.Y - fpx(4), name.X + name.Width + fpx(6), name.Y + name.Height + fpx(4), kUnderPrimary}};
    look.feather = fpx(28);
    ++g_bar.look_serial;
}

// What the overlay's glass wants of the frame now (its pieces up, the full area for the question or the X under the
// pointer) is said to the render thread; nothing when nothing is up.
void glass_wish();

// The notice and a counter in a top corner, placed again for the bar's coming or going (under it, or back up).
void notice_frame();
void move_for_bar() {
    fps_place_now();
    if (g_notice_up) notice_frame();
}

// The bar gone: hidden, its timer stopped, nothing under the pointer or held on it.
void hide_bar() {
    if (!g_bar.window) return;
    const bool was = g_bar_up;
    if (showing()) ShowWindow(g_bar.window, SW_HIDE);
    g_bar_up = false;
    KillTimer(g_bar.window, kBarTimer);
    g_bar_hover = kNone;
    // A chip held as it goes is let go of without acting: forgotten before the capture goes, so that the bar's
    // WM_CAPTURECHANGED finds nothing held and does not draw the bar again.
    const bool held = g_bar_pressed != kNone;
    g_bar_pressed = kNone;
    if (held && GetCapture() == g_bar.window) ReleaseCapture();
    if (was) {
        move_for_bar();
        glass_wish();
    }
}

// Whether the mouse's pointer is on the bar's strip at the top of the game's area (shown by a finger, it is not until
// the mouse moves).
bool pointer_on_bar() {
    if (g_bar_by_touch || !g_bar_up) return false;
    POINT p{};
    GetCursorPos(&p);
    const RECT a = area();
    return p.x >= a.left && p.x < a.right && p.y >= a.top && p.y < a.top + bar_height();
}

// The bar at the opacity its time gives it (whole while the pointer is on it and for g_bar_stay after, then fading),
// at the top of the game's area, or hidden once it faded or while the question is up; its one timer set for its next
// look.
void bar_frame() {
    if (!g_bar.window) return;
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
    // The kept look (made again only when it changed) and the picture over the frame behind (made again only when
    // either changed), shown again only when it, its opacity or its place changed.
    bar_look();
    g_bar.x = 0;
    g_bar.y = 0;
    const auto byte = static_cast<BYTE>(alpha * 255);
    const bool changed = pane_draw(g_bar);
    static RECT shown_at{};
    const RECT a = area();
    if (changed || g_bar.alpha != byte || shown_at.left != a.left || shown_at.top != a.top || !g_bar_up) {
        g_bar.alpha = byte;
        pane_show(g_bar);
        shown_at = a;
    }
    if (!g_bar_up) {
        if (showing()) ShowWindow(g_bar.window, SW_SHOWNOACTIVATE);
        g_bar_up = true;
        // The notice and a counter at the top move under it; the frame behind it is wanted from now on.
        move_for_bar();
        glass_wish();
    }
    // Fading: the next step. Whole: the next look at the pointer, or the fade's start if that comes first.
    const UINT64 next = alpha < 1 ? kBarStepMs : std::min(kBarLookMs, g_bar_stay - idle + 1);
    SetTimer(g_bar.window, kBarTimer, static_cast<UINT>(std::max<UINT64>(1, next)), nullptr);
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
            g_bar_coming = false;
            if (pointer_at_edge()) reveal(kBarStayMs);
            else glass_wish();
        }
        return 0;
    case WM_NCHITTEST: {
        // The shadow under the bar is no part of it: the game under it keeps its clicks.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        ScreenToClient(h, &p);
        if (p.y >= bar_height()) return HTTRANSPARENT;
        break;
    }
    case WM_MOUSEMOVE: {
        // A mouse's own move: the pointer is the mouse's again (a finger's moves are Windows' copies, marked).
        if (!from_touch()) g_bar_by_touch = false;
        // The chip under the pointer lights up.
        const int now = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
        if (now != g_bar_hover) {
            g_bar_hover = now;
            bar_frame();
            // On the X, the whole frame is read ahead: the question that may follow has its backdrop at once.
            glass_wish();
        }
        return 0;
    }
    case WM_LBUTTONDOWN:
        // Held on a chip: it looks pressed, and the bar keeps the mouse until it is let go.
        g_bar_pressed = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
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
        const int chip_now = chip_at(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
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
        if (chip_now != pressed) return 0;
        if (chip_now == kQuitChip) ask_quit();
        else if (chip_now == kScreenChip && g_hooks.toggle_fullscreen) g_hooks.toggle_fullscreen();
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

Pane g_ask;
// Whether it is up (or asked and waiting for its backdrop), the button the keys chose (Keep playing first) and what is
// under the pointer.
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
// Asked, and waiting (at most kAskWaitMs) for the render thread's read of the whole frame, which the dim blurs: the
// question shows once it is there, or bare after the wait. The read's count when it was asked for.
bool g_ask_waiting = false;
// Whether the read it shows over was made ahead (the X under the pointer).
bool g_ask_ahead = false;
unsigned g_ask_after = 0;
UINT64 g_ask_asked = 0;
constexpr UINT64 kAskWaitMs = 150;
// A read of the whole frame younger than this is taken as it is: the X under the pointer had it read ahead.
constexpr UINT64 kAskFreshMs = 250;
// The dimmed game behind the card (opaque, the area's size) and the card's own glass over it.
std::unique_ptr<Canvas> g_ask_dim;
std::uint64_t g_ask_dim_hash = 1;
Look g_card;
Backdrop g_card_backdrop;
bool g_card_have = false;
// What the picture was last made with (its choice, the pointer's place, the press, the scale, the dim): a move of the
// window with the same look only moves it.
int g_ask_drawn_choice = -1, g_ask_drawn_hover = -1, g_ask_drawn_pressed = -1;
float g_ask_drawn_scale = 0;
std::uint64_t g_ask_drawn_dim = 0;

// The game held still while the question is up or the window is minimised, and let go on when neither is: the window
// is told only of a change.
void update_hold() {
    const bool want = (g_asking && !g_ask_waiting) || g_minimised_hold;
    if (want == g_held) return;
    g_held = want;
    if (g_hooks.hold) g_hooks.hold(want);
}

// The question's layout in the game's area: the card in the middle, its title and the line under it, its thin X, its
// two buttons.
struct AskLayout {
    RectF card, title, text, close, keep, quit;
    // The game's line under the title: from x0 to x1 at row y.
    float line_x0 = 0, line_x1 = 0, line_y = 0;
};
AskLayout ask_layout() {
    // Within the game's area, however large Windows' scale.
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
const wchar_t* ask_text() { return g_korean ? L"곡 도중에 끝내면 기록이 남지 않아요." : L"Quitting mid-song loses that song's record."; }
const wchar_t* keep_label() { return g_korean ? L"계속하기" : L"Keep playing"; }
const wchar_t* quit_label() { return g_korean ? L"게임 끝내기" : L"Quit the game"; }

// The card's look as it is now (its choice, the pointer, the press), in a window around the card: glass with the game's
// corners (6) and bevel, its title bold and centred with the game's green line under it, its line regular, Keep playing
// as the game's green button and Quit the game as its grey tab, both with white bold words, the keys' choice as the game
// marks a chosen card (a lime border and glow).
void card_look(const AskLayout& l) {
    const AskScale cap;
    // The card's window: the card with its shadow's room, within the game's area.
    const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
    const int w = win.right - win.left, h = win.bottom - win.top;
    const float ox = static_cast<float>(win.left), oy = static_cast<float>(win.top);
    auto at = [&](RectF r) { return RectF(r.X - ox, r.Y - oy, r.Width, r.Height); };
    const float radius = fpx(6);
    const RectF card = at(l.card);
    pane_shape(g_card, w, h, card, radius);
    g_card.tint = kTintCard;
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(g_card, surface));
    edge(*g, card, radius);
    bevel(*g, card, radius, 40, 90);
    // The game's green line under the title, fading out toward its ends.
    game_line(*g, l.line_x0 - ox, l.line_x1 - ox, l.line_y - oy, game::kLine);
    // The title, bold, and the quiet line under it, regular, both centred.
    auto title_font = font(Weight::kBold, fpx(19), g_korean);
    auto text_font = font(Weight::kRegular, fpx(15), g_korean);
    say_centred(*g, ask_title(), *title_font, tone::kPrimary, at(l.title));
    say_centred(*g, ask_text(), *text_font, tone::kSecondary, at(l.text));
    // The thin X: a faint round light behind it under the pointer, brighter itself then.
    const RectF close = at(l.close);
    if (g_ask_hover == kClose) {
        SolidBrush lit(Color(g_ask_pressed == kClose ? 20 : 30, 255, 255, 255));
        g->FillEllipse(&lit, close);
    }
    Pen thin(g_ask_hover == kClose ? tone::kPrimary : Color(200, 0xF4, 0xF6, 0xF8), fpx(1.5f));
    thin.SetStartCap(LineCapRound);
    thin.SetEndCap(LineCapRound);
    cross(*g, thin, close.X + close.Width / 2, close.Y + close.Height / 2, fpx(7));
    // The two buttons; under the pointer each lights, held each is pressed in.
    const bool keep_lit = g_ask_hover == kKeep, quit_lit = g_ask_hover == kQuit;
    const bool keep_in = keep_lit && g_ask_pressed == kKeep, quit_in = quit_lit && g_ask_pressed == kQuit;
    const RectF keep = at(l.keep), quit = at(l.quit);
    green_button(*g_card.fore, *g, keep, keep_lit, keep_in, g_choice == kKeep);
    tab_button(*g_card.fore, *g, quit, quit_lit, quit_in, g_choice == kQuit);
    auto label = font(Weight::kBold, fpx(16), g_korean);
    const float down = std::max(1.0f, fpx(1));
    say_centred(*g, keep_label(), *label, Color(255, 255, 255, 255), RectF(keep.X, keep.Y + (keep_in ? down : 0), keep.Width, keep.Height));
    say_centred(*g, quit_label(), *label, Color(255, 255, 255, 255), RectF(quit.X, quit.Y + (quit_in ? down : 0), quit.Width, quit.Height));
    // The words' zones: the title and the line, as dark as the quiet line needs; Quit the game's grey, which lets a
    // little of the glass through, as dark as white words need.
    const RectF title = at(l.title), text = at(l.text);
    g_card.zones = {Look::Zone{text.X - fpx(4), title.Y - fpx(4), text.X + text.Width + fpx(4), text.Y + text.Height + fpx(4), kUnderSecondary},
                    Look::Zone{quit.X, quit.Y, quit.X + quit.Width, quit.Y + quit.Height, kUnderWhite}};
    g_card.feather = fpx(20);
}

// The dimmed, blurred game behind the card, from a read of the whole frame (the counter and the notice laid over it,
// as they lie under the dim), made again only when that read changed; the bare dim without one.
void ask_dim() {
    const int w = area_w(), h = area_h();
    Backdrop whole;
    const bool have = backdrop_from(*g_shots, glass::Rect{0, 0, w, h}, 0, whole);
    const std::uint64_t hash = have ? whole.hash : 0;
    if (g_ask_dim && g_ask_dim->w == w && g_ask_dim->h == h && g_ask_dim_hash == hash) return;
    if (!g_ask_dim || g_ask_dim->w != w || g_ask_dim->h != h) g_ask_dim = std::make_unique<Canvas>(w, h);
    g_ask_dim_hash = hash;
    if (have) {
        // The other pieces under the dim: the counter and the notice, as the screen shows them now.
        if (g_fps_corner && g_fps.picture) stamp(whole, *g_fps.picture, g_fps.x, g_fps.y);
        if (g_notice_up && g_notice.picture) stamp(whole, *g_notice.picture, g_notice.x, g_notice.y);
        // The card's own frame: the dim's, blurred on to the card's blur (their blurs add as squares) and pushed out.
        g_card_backdrop = whole;
        soften(g_card_backdrop, std::sqrt(fpx(kDimBlur) * fpx(kDimBlur) + fpx(kGlassBlur) * fpx(kGlassBlur)), kGlassSaturation, kDim);
        g_card_have = true;
        soften(whole, fpx(kDimBlur), 1.0f, kDim);
    } else {
        g_card_have = false;
    }
    // Without a frame, a deeper plain dim: the game shows through it unblurred.
    backdrop_fill(*g_ask_dim, have ? &whole : nullptr, 0.6f);
}

void draw_ask() {
    const int w = area_w(), h = area_h();
    if (w <= 1 || h <= 1) return;
    // Within the game's area, however large Windows' scale: the card and all in it.
    const AskScale cap;
    ask_dim();
    // The same look over the same dim at the same size: only its place on the screen changes.
    if (g_ask.picture && g_ask.picture->w == w && g_ask.picture->h == h && g_ask_drawn_choice == g_choice && g_ask_drawn_hover == g_ask_hover &&
        g_ask_drawn_pressed == g_ask_pressed && g_ask_drawn_scale == scale() && g_ask_drawn_dim == g_ask_dim_hash) {
        pane_show(g_ask);
        return;
    }
    g_ask_drawn_choice = g_choice;
    g_ask_drawn_hover = g_ask_hover;
    g_ask_drawn_pressed = g_ask_pressed;
    g_ask_drawn_scale = scale();
    g_ask_drawn_dim = g_ask_dim_hash;
    if (!g_ask.picture || g_ask.picture->w != w || g_ask.picture->h != h) g_ask.picture = std::make_unique<Canvas>(w, h);
    if (!g_ask.picture->bits || !g_ask_dim->bits) return;
    // The dim, then the card over it, in its window.
    std::memcpy(g_ask.picture->bits, g_ask_dim->bits, static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 4);
    const AskLayout l = ask_layout();
    card_look(l);
    const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
    compose(*g_ask.picture, win.left, win.top, g_card, g_card_have ? &g_card_backdrop : nullptr, win.left, win.top);
    g_ask.x = 0;
    g_ask.y = 0;
    g_ask.alpha = 255;
    pane_show(g_ask);
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

// A line for the player's log, when the window gave the overlay a way to it.
void note(const char* line) {
    if (g_hooks.log) g_hooks.log(line);
}

// The question shown: over the dimmed game, above everything else of the overlay, the game held.
void show_ask() {
    g_ask_waiting = false;
    draw_ask();
    // Said once a question: whether the frame behind it was read (ahead, while the X was under the pointer, or once
    // asked), and how long after it was asked it showed, its drawing included.
    char line[200];
    std::snprintf(line, sizeof line, "player: glass: the question over %s, shown %llu ms after it was asked",
                  !g_card_have ? "the bare dim (no read of the frame came)" : g_ask_ahead ? "the frame read ahead" : "the frame read for it",
                  static_cast<unsigned long long>(GetTickCount64() - g_ask_asked));
    note(line);
    if (showing()) {
        ShowWindow(g_ask.window, SW_SHOWNOACTIVATE);
        // Above everything else of the overlay: the frame counter and the notice stay under its dim.
        SetWindowPos(g_ask.window, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    }
    update_hold();
}

// The question gone; the game goes on (unless minimised), or ends when `quit`.
void answer(bool quit) {
    if (!g_asking) return;
    g_asking = false;
    g_ask_waiting = false;
    if (showing()) ShowWindow(g_ask.window, SW_HIDE);
    update_hold();
    glass_wish();
    if (quit && g_hooks.quit) g_hooks.quit();
}

LRESULT CALLBACK ask_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
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

// ---- the notice's look and steps

// The notice's look for "title\ndetail": a glass card with the broadcast's badge on its left (red LIVE while live,
// grey once ended, each with its soft glow), the title over where to watch; its glass at `glass` of its window, which
// this sets, as the game's area allows.
void notice_look(const std::string& text, bool live) {
    const std::wstring all = wide(text);
    const std::size_t cut = all.find(L'\n');
    std::wstring title = all.substr(0, cut), detail = cut == std::wstring::npos ? L"" : all.substr(cut + 1);
    auto title_font = font(Weight::kBold, fpx(16), g_korean);
    auto detail_font = font(Weight::kRegular, fpx(13), g_korean);
    auto badge_font = font(Weight::kBold, fpx(11), g_korean);
    const std::wstring badge = live ? L"LIVE" : (g_korean ? L"방송 종료" : L"ENDED");
    // The room inside the card: to the badge, between it and the words, after the words; the badge's own, the game's tag
    // (as its MY RANK), whose slanted right end takes a little more room.
    const float pad = fpx(16), gap = fpx(12), after = fpx(20), badge_h = fpx(22), badge_pad = fpx(9);
    const float slant = badge_h * 0.36f;
    const float badge_w = measure(badge, *badge_font).Width + badge_pad * 2 + (live ? fpx(0.66f) * 4 : 0) + slant;
    // The words' room: within 560 at 720 lines, and within the game's area however small its window; a long server name
    // wraps there, into even lines. A counter in a top corner keeps its corner: the card, centred, stays clear of it.
    const int aw = area_w();
    float beside = pad + badge_w + gap + after + 2 * px(kRoomSide);
    if (g_fps_corner == 1 || g_fps_corner == 2) {
        const FpsMetrics m = fps_metrics();
        const POINT at = fps_place(static_cast<int>(m.w), static_cast<int>(m.h));
        // How far in from its side the counter reaches, on both sides, with a gap.
        const float reach = g_fps_corner == 1 ? static_cast<float>(at.x) + m.w : static_cast<float>(aw - at.x);
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
    // Its place: centred at the top of the game's area, 16 down, under the bar while that is up.
    const int gx = (aw - static_cast<int>(glass_w)) / 2, gy = px(16) + top_room();
    const RECT win = window_around(gx, gy, static_cast<int>(glass_w), static_cast<int>(glass_h));
    g_notice.x = win.left;
    g_notice.y = win.top;
    Look& look = g_notice.look;
    const int w = win.right - win.left, h = win.bottom - win.top;
    const RectF glass(static_cast<REAL>(gx - win.left), static_cast<REAL>(gy - win.top), glass_w, glass_h);
    const float radius = fpx(6);
    pane_shape(look, w, h, glass, radius);
    look.tint = kTintPiece;
    std::unique_ptr<Bitmap> surface;
    std::unique_ptr<Graphics> g(fresh_fore(look, surface));
    // The badge in the middle of the glass's height: the game's tag, nearly square on its left, its right end slanted
    // down to the left; red while live (Windows' close red, white bold words at 5:1 and more), grey once ended.
    const RectF tag(glass.X + pad, glass.Y + (glass_h - badge_h) / 2, badge_w, badge_h);
    GraphicsPath tag_path;
    {
        const float corner = fpx(2);
        tag_path.AddLine(tag.X + corner, tag.Y, tag.X + tag.Width, tag.Y);
        tag_path.AddLine(tag.X + tag.Width, tag.Y, tag.X + tag.Width - slant, tag.Y + tag.Height);
        tag_path.AddLine(tag.X + tag.Width - slant, tag.Y + tag.Height, tag.X + corner, tag.Y + tag.Height);
        tag_path.AddArc(tag.X, tag.Y + tag.Height - corner * 2, corner * 2, corner * 2, 90, 90);
        tag_path.AddArc(tag.X, tag.Y, corner * 2, corner * 2, 180, 90);
        tag_path.CloseFigure();
    }
    edge(*g, glass, radius);
    bevel(*g, glass, radius, 40, 90);
    // The game's green line along its foot while live, fading out toward both ends; none once the broadcast ended.
    if (live) game_line(*g, glass.X + radius, glass.X + glass.Width - radius, glass.Y + glass.Height - std::max(1.0f, fpx(1)), game::kLine);
    {
        const Color top = live ? game::kRedTop : Color(255, 0x72, 0x79, 0x86), foot = live ? game::kRedFoot : Color(255, 0x56, 0x5C, 0x67);
        LinearGradientBrush fill(PointF(0, tag.Y - 1), PointF(0, tag.Y + tag.Height + 1), top, foot);
        g->FillPath(&fill, &tag_path);
    }
    // Its word, spaced a little as a badge's is, white and bold, in the part left of its slant.
    {
        const float spacing = live ? fpx(0.66f) : 0.0f;
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
    ++g_notice.look_serial;
    g_notice_room = top_room();
    g_notice_area_w = aw;
    g_notice_area_h = area_h();
    g_notice_scale = scale();
}

void notice_frame() {
    if (!g_notice_up) return;
    const UINT64 t = GetTickCount64() - g_notice_shown;
    float alpha = 1, drop = 0;
    if (t < kSlideMs) {
        // In: down from a little above, fading in, easing out.
        const float k = static_cast<float>(t) / kSlideMs;
        const float ease = 1 - (1 - k) * (1 - k) * (1 - k);
        alpha = ease;
        drop = (1 - ease) * fpx(kSlide);
    } else if (t > kSlideMs + kStayMs) {
        alpha = 1 - std::min(1.0f, static_cast<float>(t - kSlideMs - kStayMs) / kFadeMs);
    }
    // Gone only once the fade out is over: the first frame of the slide in is transparent as well.
    if (alpha <= 0 && t > kSlideMs) {
        KillTimer(g_notice.window, kNoticeTimer);
        if (showing()) ShowWindow(g_notice.window, SW_HIDE);
        g_notice_up = false;
        glass_wish();
        return;
    }
    // Its look again for a new place (the bar came or went) or a new size of the game's area.
    if (g_notice_room != top_room() || g_notice_area_w != area_w() || g_notice_area_h != area_h() || g_notice_scale != scale()) {
        notice_look(g_notice_text, g_notice_live);
        glass_wish();
    }
    // The picture over the frame at its resting place; the slide moves the window alone (the blur hides the difference).
    pane_draw(g_notice);
    const int rest = g_notice.y;
    g_notice.y = rest - static_cast<int>(drop);
    g_notice.alpha = static_cast<BYTE>(alpha * 255);
    pane_show(g_notice);
    g_notice.y = rest;
    // The next step: every 15 ms while it slides or fades; while it stays, once, when the fade begins.
    const bool staying = t >= kSlideMs && t < kSlideMs + kStayMs;
    SetTimer(g_notice.window, kNoticeTimer, staying ? static_cast<UINT>(kSlideMs + kStayMs - t) : 15, nullptr);
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

// ---- the frame behind the glass

// The overlay's clock for its glass: a window of messages alone, whose timer looks for new reads while a piece is up.
HWND g_clock = nullptr;
constexpr UINT_PTR kGlassTimer = 5;
// At most 20 times a second; 15 ms apart while the question waits for its read.
constexpr UINT kGlassMs = 50, kGlassWaitMs = 15;
bool g_glass_ticking = false;
UINT g_glass_every = 0;

// A piece's window grown by the blur's reach, in the game's window.
glass::Rect with_reach(const Pane& p) {
    return glass::Rect{p.x - blur_reach(), p.y - blur_reach(), p.look.w + 2 * blur_reach(), p.look.h + 2 * blur_reach()};
}

void glass_tick();

void glass_wish() {
    const int w = area_w(), h = area_h();
    std::vector<glass::Rect> rects;
    // The whole frame for the question, or ahead of it while the X is under the pointer or held.
    const bool whole = g_asking || (g_bar_up && (g_bar_hover == kQuitChip || g_bar_pressed == kQuitChip));
    if (whole) {
        rects.push_back(glass::Rect{0, 0, w, h});
    } else {
        // The bar's window, up or about to come: the game's width, the bar and its shadow's room.
        if (g_bar_up || g_bar_coming) {
            rects.push_back(glass::Rect{-blur_reach(), -blur_reach(), w + 2 * blur_reach(), bar_height() + px(kRoomBottom) + 2 * blur_reach()});
        }
        if (g_notice_up) rects.push_back(with_reach(g_notice));
        if (g_fps_corner && g_fps.window) rects.push_back(with_reach(g_fps));
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
    // The clock runs while anything is wanted: quicker while the question waits for its read.
    const UINT every = g_ask_waiting ? kGlassWaitMs : kGlassMs;
    if (!rects.empty() && g_clock && (!g_glass_ticking || g_glass_every != every)) {
        g_glass_ticking = true;
        g_glass_every = every;
        SetTimer(g_clock, kGlassTimer, every, nullptr);
    } else if (rects.empty() && g_glass_ticking && g_clock) {
        g_glass_ticking = false;
        KillTimer(g_clock, kGlassTimer);
    }
}

// Each piece up drawn again over what is behind it now, shown again where that changed it.
void glass_redraw() {
    if (g_bar_up && pane_draw(g_bar)) pane_show(g_bar);
    if (g_notice_up) notice_frame();
    if (g_fps_corner && g_fps.window && pane_draw(g_fps)) pane_show(g_fps);
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
        if (!g_asking) glass_redraw();
    }
    if (g_ask_waiting) {
        // The question shows once a read of the whole frame has come (one in flight as it was asked holds less), or bare
        // after the wait.
        Backdrop whole;
        const bool read = glass::generation() != g_ask_after && backdrop_from(*g_shots, glass::Rect{0, 0, area_w(), area_h()}, 0, whole);
        if (read || GetTickCount64() - g_ask_asked >= kAskWaitMs) {
            show_ask();
            // The game is held now: nothing new comes until it goes on; the clock back to its pace.
            glass_wish();
        }
    }
}

LRESULT CALLBACK clock_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    if (msg == WM_TIMER && w == kGlassTimer) {
        glass_tick();
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
    // The player's own faces, from its folder (Windows' own where they are not there).
    load_fonts();
    // The notice and the frame counter let clicks through to the game; the bar and the question take theirs. The counter
    // first, so that the windows made after it are above it.
    g_fps.window = make_window(L"OpenDMTQFrameCounter", fps_proc, true);
    g_notice.window = make_window(L"OpenDMTQNotice", notice_proc, true);
    g_bar.window = make_window(L"OpenDMTQBar", bar_proc, false);
    g_ask.window = make_window(L"OpenDMTQQuestion", ask_proc, false);
    // The glass's clock: a window for messages alone, never on the screen.
    WNDCLASSEXW c{};
    c.cbSize = sizeof c;
    c.lpfnWndProc = clock_proc;
    c.hInstance = GetModuleHandleW(nullptr);
    c.lpszClassName = L"OpenDMTQGlassClock";
    RegisterClassExW(&c);
    g_clock = CreateWindowExW(0, c.lpszClassName, L"", 0, 0, 0, 0, 0, HWND_MESSAGE, nullptr, c.hInstance, nullptr);
}

void notice(const std::string& text, bool live) {
    if (!g_notice.window) return;
    g_notice_text = text;
    g_notice_live = live;
    notice_look(text, live);
    // From its first step, sliding in.
    g_notice_shown = GetTickCount64();
    g_notice_up = true;
    // The frame behind it wanted from now on; until it comes, the bare tint.
    glass_wish();
    notice_frame();
    if (showing()) ShowWindow(g_notice.window, SW_SHOWNOACTIVATE);
    SetTimer(g_notice.window, kNoticeTimer, 15, nullptr);
}

void pointer_moved(int y, bool pressed) {
    g_pointer_down = pressed;
    // Not while the mouse plays (its button down), not over the question, and only at the very top edge of the game
    // (within 4 pixels at 720 lines): the game's own controls under the bar's place stay the game's while they are used.
    if (!g_bar.window || asking() || pressed) return;
    // A mouse's move: the pointer is the mouse's again.
    g_bar_by_touch = false;
    if (y >= std::max(1, px(4))) return;
    // Up already: it stays. Else the edge waits a moment, and the bar shows only if the pointer is still there then.
    if (g_bar_up) {
        reveal(kBarStayMs);
    } else {
        SetTimer(g_bar.window, kBarEdgeTimer, kBarEdgeMs, nullptr);
        // The frame behind the bar read during the wait.
        if (!g_bar_coming) {
            g_bar_coming = true;
            glass_wish();
        }
    }
}

void show_bar() {
    if (!g_bar.window || asking()) return;
    // A finger has no pointer that stays on the bar: whole for a few seconds, then fading.
    g_bar_by_touch = true;
    reveal(kBarTouchStayMs);
}

bool asking() { return g_ask.window && g_asking; }

void ask_quit() {
    if (!g_ask.window || g_asking) return;
    g_asking = true;
    // Keep playing chosen first, so that Enter at once goes on; nothing lit until the pointer moves over it.
    g_choice = kKeep;
    g_ask_hover = kNone;
    g_ask_pressed = kNone;
    // A read of the whole frame the X had made ahead (under the pointer a moment ago) is taken at once; else one is
    // asked for now, and the question shows when it comes (a few frames) or bare after kAskWaitMs. The game goes on
    // meanwhile, so that the read has a frame to read; minimised, it is held already, and the question shows at once.
    if (glass::take(g_shots_seen, g_shots)) g_shots_at = GetTickCount64();
    Backdrop whole;
    const bool fresh = backdrop_from(*g_shots, glass::Rect{0, 0, area_w(), area_h()}, 0, whole) && GetTickCount64() - g_shots_at < kAskFreshMs;
    g_ask_waiting = !fresh && !g_minimised_hold;
    g_ask_ahead = fresh;
    g_ask_after = glass::generation();
    g_ask_asked = GetTickCount64();
    hide_bar();
    // Over a minimised game it would show nowhere: the game comes back first, still held for the question.
    if (IsIconic(g_frame)) ShowWindow(g_frame, SW_RESTORE);
    glass_wish();
    if (!g_ask_waiting) show_ask();
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
    glass_wish();
}

bool ask_key(UINT vk) {
    if (!asking()) return false;
    if (vk == VK_LEFT || vk == VK_RIGHT || vk == VK_TAB) {
        // Two buttons side by side: each of these keys moves the choice to the other.
        g_choice = g_choice == kKeep ? kQuit : kKeep;
        if (!g_ask_waiting) draw_ask();
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
    if (asking() && !g_ask_waiting) draw_ask();
    // The bar across the game's top at its new width, if it is up.
    if (g_bar_up) bar_frame();
    if (g_notice_up) notice_frame();
    // The frame counter in its corner, at the new scale (a move counts nothing: its numbers stay its timer's).
    fps_place_now();
    // The frame behind them, where they are now.
    glass_wish();
}

void show_fps(int corner, FrameCount (*frames)()) {
    if (!g_fps.window || corner <= 0 || corner > 4 || !frames) return;
    g_fps_corner = corner;
    g_fps_frames = frames;
    // Shown at once, with dashes until the first half second has been counted.
    fps_frame();
    if (showing()) ShowWindow(g_fps.window, SW_SHOWNOACTIVATE);
    SetTimer(g_fps.window, kFpsTimer, kFpsMs, nullptr);
    glass_wish();
}

HCURSOR cursor(bool pressed) {
    static std::map<std::pair<int, bool>, HCURSOR> made;
    // Windows' own cursor size at this scale: 32 pixels at 96 dpi, 48 at 150 % (Windows' scale alone, as its own
    // pointer's).
    const int size = std::max(32, static_cast<int>(std::lround(32 * dpi_scale())));
    HCURSOR& c = made[{size, pressed}];
    if (!c) c = make_cursor(size, pressed);
    return c;
}

#ifdef OVERLAY_TEST_HOOKS
namespace {

// A PNG of a premultiplied picture, with its own alpha.
void save_png(Canvas& c, const std::wstring& path) {
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    Bitmap out(c.w, c.h, PixelFormat32bppARGB);
    Graphics g(&out);
    g.Clear(Color(0, 0, 0, 0));
    g.SetCompositingMode(CompositingModeSourceCopy);
    auto picture = c.surface();
    g.DrawImage(picture.get(), 0, 0, c.w, c.h);
    out.Save(path.c_str(), &png, nullptr);
}

// How long the overlay's thread takes to draw a pane's picture over a new frame behind it (the frame's blur and tint,
// the glass, its words over it), in milliseconds, the mean of a few: "time <name> <ms>" in the layout file.
void time_line(FILE* out, const char* name, Pane& p) {
    LARGE_INTEGER f{}, a{}, b{};
    QueryPerformanceFrequency(&f);
    constexpr int kRuns = 5;
    QueryPerformanceCounter(&a);
    for (int i = 0; i < kRuns; ++i) {
        // As if a new read had come: the frame behind blurred again and the picture made again.
        p.have_backdrop = false;
        p.drawn_serial = -1;
        pane_draw(p);
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

// What the render thread would read of the frame for the overlay's wish now, as the overlay's last read: a rectangle at
// a quarter of its size as a blit with a linear filter makes it, which at a quarter exactly is the mean of the 2 by 2
// pixels in the middle of each 4 by 4 (glass_capture.cpp's read). Every wanted rectangle starts on the window's
// multiples of 4, so one read of the whole frame holds the same pixels as the pieces' own reads would: the probe reads
// that one.
void test_read() {
    const int w = area_w(), h = area_h();
    // The wish as the pieces make it now, through the same exchange (the render thread is not there to read it).
    glass_wish();
    const std::vector<glass::Rect> rects = {glass::aligned(glass::Rect{0, 0, w, h}, 0, w, h)};
    auto shots = std::make_shared<std::vector<glass::Shot>>();
    for (const glass::Rect& r : rects) {
        glass::Shot s;
        s.rect = r;
        s.w = r.w / 4;
        s.h = r.h / 4;
        s.rgba.resize(static_cast<std::size_t>(s.w) * static_cast<std::size_t>(s.h) * 4);
        for (int j = 0; j < s.h; ++j) {
            for (int i = 0; i < s.w; ++i) {
                // The middle 2 by 2 of the quarter pixel's 4 by 4.
                for (int c = 0; c < 4; ++c) {
                    int sum = 0;
                    for (int dy = 1; dy <= 2; ++dy) {
                        for (int dx = 1; dx <= 2; ++dx) {
                            const int x = std::min(g_test_frame_w - 1, r.x + i * 4 + dx), y = std::min(g_test_frame_h - 1, r.y + j * 4 + dy);
                            sum += g_test_frame[(static_cast<std::size_t>(y) * static_cast<std::size_t>(g_test_frame_w) + static_cast<std::size_t>(x)) * 4 +
                                                static_cast<std::size_t>(c)];
                        }
                    }
                    s.rgba[(static_cast<std::size_t>(j) * static_cast<std::size_t>(s.w) + static_cast<std::size_t>(i)) * 4 + static_cast<std::size_t>(c)] =
                        static_cast<std::uint8_t>((sum + 2) / 4);
                }
            }
        }
        shots->push_back(std::move(s));
    }
    g_shots = std::move(shots);
    g_shots_at = GetTickCount64();
}

// One line of the layout file: a piece's picture's name and its window's place and size in the game's area.
void layout_line(FILE* out, const char* name, const Pane& p) {
    if (out) std::fprintf(out, "%s %d %d %d %d\n", name, p.x, p.y, p.picture ? p.picture->w : 0, p.picture ? p.picture->h : 0);
}

// The words the last look drew, in the game's area (its window at (x, y)): "text <picture> x y w h rrggbb" a line; then
// a fresh list for the next.
std::vector<TestText> g_test_words;
void words_lines(FILE* out, const std::string& name, int x, int y) {
    for (const TestText& t : g_test_words) {
        if (out) {
            std::fprintf(out, "text %s %.1f %.1f %.1f %.1f %02x%02x%02x\n", name.c_str(), t.box.X + static_cast<float>(x), t.box.Y + static_cast<float>(y), t.box.Width,
                         t.box.Height, t.colour.GetR(), t.colour.GetG(), t.colour.GetB());
        }
    }
    g_test_words.clear();
}

}  // namespace

void test_save(const std::wstring& prefix, const std::wstring& frame_png, bool with_words) {
    g_test_quiet = true;
    g_test_no_words = !with_words;
    // The frame behind, as the window would show it: of the game's area's size exactly.
    {
        Bitmap frame(frame_png.c_str());
        if (frame.GetLastStatus() != Ok || static_cast<int>(frame.GetWidth()) != area_w() || static_cast<int>(frame.GetHeight()) != area_h()) {
            std::fprintf(stderr, "probe: the frame is not there or not the game area's size (%dx%d)\n", area_w(), area_h());
            return;
        }
        g_test_frame_w = area_w();
        g_test_frame_h = area_h();
        g_test_frame.assign(static_cast<std::size_t>(g_test_frame_w) * static_cast<std::size_t>(g_test_frame_h) * 4, 0);
        BitmapData data{};
        Rect all(0, 0, g_test_frame_w, g_test_frame_h);
        if (frame.LockBits(&all, ImageLockModeRead, PixelFormat32bppARGB, &data) == Ok) {
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
        }
    }
    FILE* layout = _wfopen((prefix + L"layout.txt").c_str(), L"w");
    if (layout) std::fprintf(layout, "area 0 0 %d %d\nscale %.4f\n", area_w(), area_h(), static_cast<double>(scale()));
    const Hooks kept = g_hooks;
    const int kept_corner = g_fps_corner;
    // The bar in a window and in full screen (its chip's icon the other way), at rest, with each chip lit, and each held.
    for (bool full : {false, true}) {
        g_hooks.fullscreen = full ? +[] { return true; } : +[] { return false; };
        const std::wstring state = full ? L"full" : L"window";
        struct BarLook {
            int hover, pressed;
            const wchar_t* suffix;
        };
        for (const BarLook& b : {BarLook{kNone, kNone, L""}, BarLook{kScreenChip, kNone, L"-screen"}, BarLook{kQuitChip, kNone, L"-quit"},
                                 BarLook{kScreenChip, kScreenChip, L"-screen-pressed"}, BarLook{kQuitChip, kQuitChip, L"-quit-pressed"}}) {
            g_bar_hover = b.hover;
            g_bar_pressed = b.pressed;
            g_bar_up = true;
            g_test_texts = &g_test_words;
            bar_look();
            g_test_texts = nullptr;
            test_read();
            pane_draw(g_bar);
            save_png(*g_bar.picture, prefix + L"bar-" + state + b.suffix + L".png");
            if (!full && b.hover == kNone) {
                layout_line(layout, "bar", g_bar);
                time_line(layout, "bar", g_bar);
            }
            words_lines(layout, "bar-" + std::string(full ? "full" : "window") + narrow_ascii(b.suffix), g_bar.x, g_bar.y);
        }
        g_bar_hover = g_bar_pressed = kNone;
        g_bar_up = false;
    }
    g_hooks = kept;
    // The notice while live and once ended, in the server's own words (server/game/live/state.php), a server's name in
    // its place; a long name, which the card wraps within the game's width; each without the bar and under it; and the
    // long one beside a counter in either top corner.
    const std::string live_text = g_korean ? "이 플레이를 방송하고 있어요\nMy Server 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Your play is live\nWatch it now or later under LIVE on My Server";
    const std::string ended_text = g_korean ? "방송을 마쳤어요\nMy Server 사이트 LIVE에서 다시 볼 수 있어요"
                                            : "Your broadcast has ended\nWatch the replay under LIVE on My Server";
    const std::string long_text = g_korean ? "이 플레이를 방송하고 있어요\nOpenDMTQ Community Server Seoul Central 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요"
                                           : "Your play is live\nWatch it now or later under LIVE on OpenDMTQ Community Server Seoul Central";
    struct NoticeCase {
        const char* name;
        const std::string* text;
        bool live, bar;
        int corner;
    };
    for (const NoticeCase& n : {NoticeCase{"notice-live", &live_text, true, false, 0}, NoticeCase{"notice-ended", &ended_text, false, false, 0},
                                NoticeCase{"notice-long", &long_text, true, false, 0}, NoticeCase{"notice-live-bar", &live_text, true, true, 0},
                                NoticeCase{"notice-long-fps1", &long_text, true, false, 1}, NoticeCase{"notice-long-fps2", &long_text, true, false, 2}}) {
        g_test_bar_up = n.bar;
        g_fps_corner = n.corner;
        g_test_texts = &g_test_words;
        notice_look(*n.text, n.live);
        g_test_texts = nullptr;
        g_notice_up = true;
        test_read();
        pane_draw(g_notice);
        save_png(*g_notice.picture, prefix + wide(n.name) + L".png");
        layout_line(layout, n.name, g_notice);
        words_lines(layout, n.name, g_notice.x, g_notice.y);
        if (std::string(n.name) == "notice-live") time_line(layout, "notice", g_notice);
        g_notice_up = false;
        g_test_bar_up = false;
        g_fps_corner = kept_corner;
    }
    // The frame counter in each corner, at 240 frames a second; at the top, with the bar up as well; and its other
    // numbers in the top right.
    for (int corner = 1; corner <= 4; ++corner) {
        for (bool bar : {false, true}) {
            if (bar && corner > 2) continue;
            g_fps_corner = corner;
            g_test_bar_up = bar;
            g_fps_shown = 240;
            g_fps_shown_ms = 4.2f;
            g_fps_drawn = -2;
            g_test_texts = &g_test_words;
            fps_place_now();
            g_test_texts = nullptr;
            test_read();
            pane_draw(g_fps);
            char name[32];
            std::snprintf(name, sizeof name, "fps%d%s", corner, bar ? "-bar" : "");
            save_png(*g_fps.picture, prefix + wide(name) + L".png");
            layout_line(layout, name, g_fps);
            words_lines(layout, name, g_fps.x, g_fps.y);
            if (corner == 2 && !bar) time_line(layout, "fps", g_fps);
        }
    }
    g_test_bar_up = false;
    struct Count {
        int fps;
        float ms;
        const char* name;
    };
    for (const Count& n : {Count{-1, 0, "fps-dash"}, Count{0, 0, "fps-0"}, Count{60, 16.7f, "fps-60"}, Count{999, 1.0f, "fps-999"}}) {
        g_fps_corner = 2;
        g_fps_shown = n.fps;
        g_fps_shown_ms = n.ms;
        g_fps_drawn = -2;
        g_test_texts = &g_test_words;
        fps_place_now();
        g_test_texts = nullptr;
        test_read();
        pane_draw(g_fps);
        save_png(*g_fps.picture, prefix + wide(n.name) + L".png");
        layout_line(layout, n.name, g_fps);
        words_lines(layout, n.name, g_fps.x, g_fps.y);
    }
    g_fps_corner = 0;
    // The question: each choice of the keys, the pointer on each button and on the thin X, each button held; over the
    // dimmed game (the dim saved once, the card's window over it for each look).
    g_asking = true;
    struct Ask {
        int choice, hover, pressed;
        const char* name;
    };
    test_read();
    bool dim_saved = false;
    for (const Ask& a : {Ask{kKeep, kNone, kNone, "ask-keep"}, Ask{kQuit, kNone, kNone, "ask-quit"}, Ask{kKeep, kKeep, kNone, "ask-hover-keep"},
                         Ask{kKeep, kQuit, kNone, "ask-hover-quit"}, Ask{kKeep, kClose, kNone, "ask-hover-close"},
                         Ask{kKeep, kKeep, kKeep, "ask-pressed-keep"}, Ask{kKeep, kQuit, kQuit, "ask-pressed-quit"}}) {
        g_choice = a.choice;
        g_ask_hover = a.hover;
        g_ask_pressed = a.pressed;
        g_test_texts = &g_test_words;
        draw_ask();
        g_test_texts = nullptr;
        if (!dim_saved && g_ask_dim) {
            save_png(*g_ask_dim, prefix + L"ask-dim.png");
            dim_saved = true;
        }
        // The card's window cut out of the whole picture: the rest is the dim.
        const AskScale cap;
        const AskLayout l = ask_layout();
        const RECT win = window_around(static_cast<int>(l.card.X), static_cast<int>(l.card.Y), static_cast<int>(l.card.Width), static_cast<int>(l.card.Height));
        Canvas part(win.right - win.left, win.bottom - win.top);
        if (part.bits && g_ask.picture && g_ask.picture->bits) {
            for (int y = 0; y < part.h; ++y) {
                std::memcpy(static_cast<std::uint8_t*>(part.bits) + static_cast<std::size_t>(y) * static_cast<std::size_t>(part.w) * 4,
                            static_cast<std::uint8_t*>(g_ask.picture->bits) +
                                (static_cast<std::size_t>(win.top + y) * static_cast<std::size_t>(g_ask.picture->w) + static_cast<std::size_t>(win.left)) * 4,
                            static_cast<std::size_t>(part.w) * 4);
            }
            save_png(part, prefix + wide(a.name) + L".png");
            if (layout) std::fprintf(layout, "%s %ld %ld %d %d\n", a.name, win.left, win.top, part.w, part.h);
            words_lines(layout, a.name, static_cast<int>(win.left), static_cast<int>(win.top));
        }
    }
    {
        // The question drawn afresh over a new read: the whole frame's dim and the card's glass, then its look.
        LARGE_INTEGER f{}, a{}, b{};
        QueryPerformanceFrequency(&f);
        QueryPerformanceCounter(&a);
        g_ask_dim_hash = 1;
        g_ask_drawn_choice = -1;
        draw_ask();
        QueryPerformanceCounter(&b);
        if (layout) std::fprintf(layout, "time ask %.3f\n", static_cast<double>(b.QuadPart - a.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart));
        // A new look over the same dim (the pointer onto another button).
        QueryPerformanceCounter(&a);
        g_ask_hover = g_ask_hover == kKeep ? kQuit : kKeep;
        draw_ask();
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
    g_asking = false;
    g_choice = kKeep;
    g_ask_hover = g_ask_pressed = kNone;
    if (layout) {
        for (int which : {kScreenChip, kQuitChip}) {
            const RectF r = chip_rect(which, area_w());
            std::fprintf(layout, "%s %.0f %.0f %.0f %.0f\n", which == kQuitChip ? "chip-quit" : "chip-screen", r.X, r.Y, r.Width, r.Height);
        }
        std::fclose(layout);
    }
    g_fps_corner = kept_corner;
    g_test_quiet = false;
    g_test_no_words = false;
}

void test_set_dpi(float scale) { g_test_dpi = scale; }


#endif

}  // namespace player::overlay
