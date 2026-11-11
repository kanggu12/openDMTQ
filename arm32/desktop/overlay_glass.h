// The overlay's frosted glass (overlay_win32.cpp draws its pieces with it), as Fluent's acrylic is made: the game's own
// frame behind a piece, blurred and a little more saturated; a charcoal tint over it; a luminosity layer, light at the
// top and gone at the bottom; a fine monochrome noise that keeps the gradients from banding; a thin light edge, lighter
// along the top; and a soft shadow under it all. Where words sit on the glass, the tint deepens there as much as the
// frame behind needs for the words to keep 4.5:1. The frame comes from the render thread (glass_capture.h) at a quarter of
// the window's pixels; the blur, the tint and the rest are done here, on the overlay's thread, on the CPU.
//
// Also the overlay's faces: Pretendard (regular, semibold, bold) for its words and DMTQ Wide for the bar's name where
// its wordmark's pictures are not there, both under the SIL Open Font License, loaded for the player alone from its own
// folder (fonts\ beside the program); Windows' own faces where they are not there. And the wordmark's pictures
// (images\ beside the program).
#pragma once

#include "canvas_win32.h"
#include "glass_capture.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace player::overlay {

// ---- the look's colours, at 720 lines (the sizes go through the overlay's px())

namespace tone {
// The words: white enough on the charcoal glass, and the quieter grey of a line that explains (both kept at 4.5:1 over
// the worst frame by the tint under them).
inline const Gdiplus::Color kPrimary(255, 0xF4, 0xF6, 0xF8);
inline const Gdiplus::Color kSecondary(255, 0xB8, 0xC0, 0xC8);
// The game's lime: the counter's label and border, the handle's line with the pointer on it.
inline const Gdiplus::Color kLime(255, 0x8C, 0xF2, 0x3D);
}  // namespace tone

// The tint: the charcoal of the game's own panels, and how much of it covers the frame on each kind of glass.
constexpr std::uint8_t kTintR = 0x15, kTintG = 0x18, kTintB = 0x1B;
// The bar, the notice, the chips and the counter; the question's card; and any glass with no frame behind it yet, which
// then lets the game through unblurred and must be solid enough to read on its own.
constexpr float kTintPiece = 0.60f, kTintCard = 0.72f, kTintBare = 0.88f;

// The most a background may light the words on it (relative luminance), for each kind of words to keep 4.6:1 (4.5 and a
// little for the noise): the primary words, the secondary words.
constexpr float kUnderPrimary = 0.160f, kUnderSecondary = 0.074f;

// ---- the faces

// The weights of Pretendard the overlay uses.
enum class Weight { kRegular, kSemiBold, kBold };
// Pretendard at `px` pixels in that weight (Windows' own UI face in the language's script where the player's are not
// there); DMTQ Wide, the launcher's wordmark face, likewise (Windows' UI face in bold where not).
std::unique_ptr<Gdiplus::Font> font(Weight weight, float px, bool korean);
std::unique_ptr<Gdiplus::Font> wide_font(float px);
// Loads the player's own faces from fonts\ beside the program, once, after GDI+ has started; whether they were there.
bool load_fonts();

// ---- the wordmark

// Loads the OpenDMTQ wordmark's pictures from images\ beside the program (bar-wordmark-<percent>.png, drawn by the
// launcher's own code: arm32/desktop/assets/make_wordmark.py), once, after GDI+ has started; whether any was there.
bool load_art();
// The wordmark's picture for the overlay's `scale` (1 at 720 lines and 96 dpi): the one drawn for that scale, or the
// next larger one, which the caller draws down to it (the largest beyond the last); its own scale in `drawn_for`. Null
// when none was loaded (the bar sets its name in words then).
Gdiplus::Bitmap* wordmark(float scale, float& drawn_for);

// ---- the frame behind a piece

// A frame's pixels behind a piece: the window's pixels from (x, y) of the game's window, a quarter of them each way,
// as RGB bytes, top row first; after soften(), blurred and tinted toward saturation.
struct Backdrop {
    int x = 0, y = 0, w = 0, h = 0;
    std::vector<std::uint8_t> rgb;
    // What it was made from (the read's pixels and the place): the same again draws the same picture.
    std::uint64_t hash = 0;
};

// The frame's pixels around the rectangle `r` of the game's window, `margin` more on every side (the blur's reach), from
// what the render thread read: the read that holds `r` whole, its edge repeated where the margin goes past it. False
// when no read holds it.
bool backdrop_from(const std::vector<glass::Shot>& shots, const glass::Rect& r, int margin, Backdrop& out);
// Whether a read holds the rectangle `r` whole, as backdrop_from takes it, without copying anything: the window's
// thread asks it, the overlay's painter copies.
bool holds(const std::vector<glass::Shot>& shots, const glass::Rect& r);
// Another of the overlay's pictures (premultiplied, at (x, y) of the game's window) laid over the frame's pixels, as
// what lies under the question's dim with the game: blurred and dimmed with it after.
void stamp(Backdrop& b, Canvas& picture, int x, int y);
// Blurred as by a Gaussian of `sigma` of the window's pixels (three box blurs), its colour pushed out by `saturation`
// (1.15: 15 % more), and dimmed toward black by `dim` (0.4: 40 %).
void soften(Backdrop& b, float sigma, float saturation, float dim);

// ---- a piece of glass

// A piece's picture as its look makes it, apart from the frame behind: the glass's shape (its coverage, smooth at the
// edges), the shadow under it, what is drawn on it (words, lines, chips: `fore`, premultiplied), where words sit on it
// (the tint deepens there), the tint, and the glass's top and height for the light layer. Made again only when the
// look changes; the frame behind changes the picture through compose().
struct Look {
    int w = 0, h = 0;
    std::vector<std::uint8_t> cover, shade;
    std::unique_ptr<Canvas> fore;
    struct Zone {
        // The words' box in the window's pixels and the most light they can have under them.
        float x0 = 0, y0 = 0, x1 = 0, y1 = 0, under = kUnderPrimary;
    };
    std::vector<Zone> zones;
    // How far beyond its words a deeper tint fades out, in the window's pixels.
    float feather = 10;
    float tint = kTintPiece;
    // The tint's colour at the glass's top and at its foot (the game's charcoal both, unless a piece takes another, as
    // the frame counter takes the game's green-black of its Q and MAX box).
    std::uint8_t tint_top[3] = {kTintR, kTintG, kTintB}, tint_foot[3] = {kTintR, kTintG, kTintB};
    float top = 0, height = 1;
    // What its shape and shadow were made for (shape() makes them again only for another).
    std::vector<float> made_for;
};

// The glass's shape as a rounded rectangle `r` (radius 0: square; `beyond`: the shape goes past the window's sides and
// top, as the bar's does) in a window of `w` by `h`, with its shadow: black at `shadow` (0.35), as blurred as a 2-sigma of
// `blur` (18 at 720 lines) and `drop` lower (4). Fills `look`'s size, coverage and shadow; the rest is the caller's.
void shape(Look& look, int w, int h, Gdiplus::RectF r, float radius, bool beyond, float shadow, float blur, float drop);
// The piece over what the picture `out` holds at (ox, oy), the look's size (transparent for a piece alone, the dimmed
// game for the question's card): the shadow, the glass over the frame `b` (null: the bare tint, kTintBare, which lets the
// game through), what is drawn on it. (x, y): the look's place in the game's window, where `b` is.
void compose(Canvas& out, int ox, int oy, const Look& look, const Backdrop* b, int x, int y);
// The dimmed, blurred game over a whole window of the game's size, from `b` (soften()'s), as the question's backdrop;
// black at `bare` (0.6) over nothing (transparent black) where there is no frame.
void backdrop_fill(Canvas& out, const Backdrop* b, float bare);

// ---- drawing on a piece

// A soft light or shadow: what `draw` fills (in white, with GDI+, in the canvas's own pixels) within `bounds`, blurred by
// `sigma`, moved by (dx, dy), in `colour` at its own alpha, added under what the canvas holds (call it before drawing
// over it). Only the bounds and the blur's reach around them are worked on.
void glow(Canvas& c, Gdiplus::RectF bounds, float sigma, float dx, float dy, const Gdiplus::Color& colour,
          const std::function<void(Gdiplus::Graphics&)>& draw);
// A rounded rectangle as a path.
void rounded(Gdiplus::GraphicsPath& path, Gdiplus::RectF r, float radius);
// What `draw` fills (with GDI+, smooth, pixels at their centres) on a picture of w by h, as each pixel's coverage from 0
// to 1, top row first: a shape's soft-edged mask, for pixels worked out by hand.
std::vector<float> coverage(int w, int h, const std::function<void(Gdiplus::Graphics&)>& draw);

// ---- the launcher's buttons (client/opendmtq_client/art.py: cut_outline, BUTTON_LOOKS, raised, sunk, button_face)

// A face's fill: one colour, or three (at its top, at 55 % of its height, at its foot), each 0xRRGGBB.
struct Fill {
    int n;
    std::uint32_t c[3];
};
namespace launcher {
// The launcher's main button (its lime, "home"): at rest, under the pointer, pressed; the dark ink of its words.
inline constexpr Fill kMain{3, {0xACF673, 0x8CF23D, 0x76CB33}}, kMainHover{3, {0xBCF98C, 0x9DF55A, 0x82D83C}},
                      kMainPressed{3, {0x9EE665, 0x7FE234, 0x6BB92E}};
inline const Gdiplus::Color kMainInk(255, 0x0D, 0x1C, 0x04);
// Its secondary button (quiet metal, "neutral"): at rest, under the pointer (a lighter plate), pressed; its words' chalk.
inline constexpr Fill kMetal{1, {0x323A44, 0, 0}}, kMetalHover{1, {0x414B57, 0, 0}}, kMetalPressed{1, {0x272E36, 0, 0}};
inline const Gdiplus::Color kMetalInk(255, 0xEE, 0xF2, 0xF6);
// The red its buttons that remove fill with under the pointer and pressed ("danger_quiet"); their words' dark ink.
inline constexpr Fill kRed{1, {0xFF5F72, 0, 0}}, kRedPressed{1, {0xE04558, 0, 0}};
inline const Gdiplus::Color kRedInk(255, 0x2B, 0x04, 0x09);
}  // namespace launcher

// A launcher button's face (art.button_face) in the canvas's pixels, w by h at (x, y), over what the canvas holds: its
// outline with the top-left and bottom-right corners cut at 45 degrees (8 at 100 %), `fill` down it; raised (a line of
// light along its top and left edges and one of shade along its foot and right, a pixel wide at 100 %, the light
// stronger on the metal's shade and the lime's light) or, `pressed`, sunk (a soft shadow inside its top and left edges,
// 3 deep at 100 %, and a faint light inside its foot). `scale` is the launcher's (1 at 100 %), the overlay's own (1 at
// 720 lines). What GDI+ drew on the canvas before must be flushed first.
void launcher_face(Canvas& c, int x, int y, int w, int h, const Fill& fill, bool pressed, float scale);
// The launcher's keyboard ring around such a face, as its dialogs draw it: the face's outline 2.5 outside it (at 100 %),
// 2 wide, in the keyboard's cyan (theme.CYAN).
void launcher_ring(Canvas& c, int x, int y, int w, int h, float scale);
// GDI+'s smooth shapes and grey smoothed text, pixels at their centres.
void smooth(Gdiplus::Graphics& g);

}  // namespace player::overlay
