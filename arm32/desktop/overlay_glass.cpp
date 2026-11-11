// The overlay's frosted glass and faces (overlay_glass.h says what they are). Everything here runs on the overlay's
// thread, on pictures of a few hundred thousand pixels at most: the frame behind arrives at a quarter of the window's
// pixels, is blurred there, tinted there, and only then spread over the window's pixels, with the noise and the edges on
// top at the window's own.
#include "overlay_glass.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

namespace player::overlay {

namespace {

using namespace Gdiplus;

// ---- the faces

// The player's own faces, each file in a collection of its own, for the player's life once loaded (GDI+ reads them from
// their collections whenever it draws). One collection of all of them would not do: GDI+ then takes the regular file
// for "Pretendard" bold and thickens it itself (measured: a third less ink than Pretendard-Bold.ttf draws).
std::unique_ptr<PrivateFontCollection> g_collections[4];
// Their families: Pretendard's regular, its semibold (a family of its own in Windows' terms) and its bold, each from its
// own file, and DMTQ Wide. Null when not there.
std::unique_ptr<FontFamily> g_regular, g_semibold, g_bold, g_wide;
bool g_fonts_tried = false;

// The folder the program is in, without its last separator ("" when Windows will not say).
std::wstring program_folder() {
    std::vector<wchar_t> buf(MAX_PATH);
    for (;;) {
        const DWORD n = GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
        if (n == 0) return L"";
        // A path longer than the buffer comes back cut: again with more room.
        if (n < buf.size()) {
            const std::wstring path(buf.data(), n);
            const std::size_t cut = path.find_last_of(L"\\/");
            return cut == std::wstring::npos ? L"" : path.substr(0, cut);
        }
        buf.resize(buf.size() * 2);
    }
}

// A family of a collection by name, or null when it is not there.
std::unique_ptr<FontFamily> family_of(const wchar_t* name, PrivateFontCollection* collection) {
    if (!collection) return nullptr;
    auto f = std::make_unique<FontFamily>(name, collection);
    return f->GetLastStatus() == Ok && f->IsAvailable() ? std::move(f) : nullptr;
}

// Windows' own face for the language's script, kept (the overlay asks for it at every drawing).
const FontFamily& windows_face(bool korean) {
    static std::unique_ptr<FontFamily> faces[2];
    auto& f = faces[korean ? 1 : 0];
    if (!f) f = face(korean);
    return *f;
}

// ---- the blur: three box blurs, as close to a Gaussian as the eye tells

// The widths of the three boxes whose blur is a Gaussian of `sigma` (the boxes of Kutskir's "fastest Gaussian blur").
std::array<int, 3> boxes(float sigma) {
    const float ideal = std::sqrt(12.0f * sigma * sigma / 3.0f + 1.0f);
    int lower = static_cast<int>(std::floor(ideal));
    // Odd widths only: a box has a middle.
    if (lower % 2 == 0) --lower;
    lower = std::max(1, lower);
    const int upper = lower + 2;
    // How many of the three take the lower width, so that their variances add up to the Gaussian's.
    const float m = (12.0f * sigma * sigma - 3.0f * static_cast<float>(lower * lower) - 12.0f * static_cast<float>(lower) - 9.0f) /
                    (-4.0f * static_cast<float>(lower) - 4.0f);
    const int lowers = static_cast<int>(std::lround(m));
    return {0 < lowers ? lower : upper, 1 < lowers ? lower : upper, 2 < lowers ? lower : upper};
}

// One box blur of `radius` along one direction of `channels` interleaved floats: `count` lines of `length` values,
// `step` apart along a line and `stride` apart between lines; the edge's value repeated beyond it.
void box_pass(std::vector<float>& v, std::vector<float>& line, int channels, int count, int length, int step, int stride, int radius) {
    if (radius <= 0 || length <= 0) return;
    const float scale = 1.0f / static_cast<float>(2 * radius + 1);
    line.resize(static_cast<std::size_t>(length));
    for (int n = 0; n < count; ++n) {
        for (int c = 0; c < channels; ++c) {
            float* first = v.data() + static_cast<std::size_t>(n) * static_cast<std::size_t>(stride) + c;
            // The line copied out, then the running sum over the box around each of its values.
            for (int i = 0; i < length; ++i) line[static_cast<std::size_t>(i)] = first[static_cast<std::size_t>(i) * static_cast<std::size_t>(step)];
            auto at = [&](int i) { return line[static_cast<std::size_t>(std::clamp(i, 0, length - 1))]; };
            float sum = 0;
            for (int i = -radius; i <= radius; ++i) sum += at(i);
            for (int i = 0; i < length; ++i) {
                first[static_cast<std::size_t>(i) * static_cast<std::size_t>(step)] = sum * scale;
                sum += at(i + radius + 1) - at(i - radius);
            }
        }
    }
}

// A Gaussian blur of `sigma` over a picture of w by h with `channels` interleaved floats.
void blur(std::vector<float>& v, int w, int h, int channels, float sigma) {
    // Under half a pixel a blur changes nothing one could see.
    if (sigma < 0.5f) return;
    std::vector<float> line;
    for (int width : boxes(sigma)) {
        const int radius = (width - 1) / 2;
        // Across each row, then down each column.
        box_pass(v, line, channels, h, w, channels, w * channels, radius);
        box_pass(v, line, channels, w, h, w * channels, channels, radius);
    }
}

// ---- the colours' light

// An sRGB byte's linear light, from a table.
float linear(int byte) {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> t{};
        for (int i = 0; i < 256; ++i) {
            const float c = static_cast<float>(i) / 255.0f;
            t[static_cast<std::size_t>(i)] = c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f);
        }
        return t;
    }();
    return table[static_cast<std::size_t>(std::clamp(byte, 0, 255))];
}

// The relative luminance of an sRGB colour of floats 0..255 (WCAG's).
float luminance(float r, float g, float b) {
    return 0.2126f * linear(static_cast<int>(r + 0.5f)) + 0.7152f * linear(static_cast<int>(g + 0.5f)) + 0.0722f * linear(static_cast<int>(b + 0.5f));
}

// The glass's colour over a frame's colour (rgb) with the tint (`tint`) at `a` and the light layer at `light`, with the
// noise at its brightest (it adds at most 2 % of white): what words on it have to stand out from at worst.
void glass_colour(const float* rgb, const float* tint, float a, float light, float out[3]) {
    for (int c = 0; c < 3; ++c) {
        const float tinted = rgb[c] * (1 - a) + tint[c] * a;
        const float lit = tinted * (1 - light) + 255.0f * light;
        out[c] = lit * 0.98f + 255.0f * 0.02f;
    }
}

// The least tint at or above `base` under which the glass over `rgb` lights words at most `under` (relative
// luminance), by halving: the tint darkens it steadily.
float tint_for(const float* rgb, const float* tint, float base, float light, float under) {
    float c[3];
    glass_colour(rgb, tint, base, light, c);
    if (luminance(c[0], c[1], c[2]) <= under) return base;
    float low = base, high = 1.0f;
    for (int i = 0; i < 10; ++i) {
        const float mid = (low + high) / 2;
        glass_colour(rgb, tint, mid, light, c);
        if (luminance(c[0], c[1], c[2]) <= under) high = mid;
        else low = mid;
    }
    return high;
}

// The light layer's strength at a row of the window: 7 % of white at the glass's top, nothing at its bottom.
float light_at(const Look& look, float y) {
    const float t = (y - look.top) / std::max(1.0f, look.height);
    return 0.07f * std::clamp(1.0f - t, 0.0f, 1.0f);
}

// The tint's colour at a row of the window: from the glass's top colour to its foot's.
void tint_at(const Look& look, float y, float out[3]) {
    const float t = std::clamp((y - look.top) / std::max(1.0f, look.height), 0.0f, 1.0f);
    for (int c = 0; c < 3; ++c) out[c] = static_cast<float>(look.tint_top[c]) + (static_cast<float>(look.tint_foot[c]) - static_cast<float>(look.tint_top[c])) * t;
}

// The fine noise over the glass: a 64-pixel tile of grey values, the same for every piece, fixed from a seed.
const std::array<std::uint8_t, 64 * 64>& noise() {
    static const std::array<std::uint8_t, 64 * 64> tile = [] {
        std::array<std::uint8_t, 64 * 64> t{};
        std::uint32_t state = 0x2545F491u;
        for (auto& v : t) {
            // A plain xorshift: even enough for a texture nobody reads.
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            v = static_cast<std::uint8_t>(state >> 24);
        }
        return t;
    }();
    return tile;
}

// The canvas's pixels as 32-bit premultiplied BGRA words.
std::uint32_t* pixels(Canvas& c) { return static_cast<std::uint32_t*>(c.bits); }

// The alpha of what `draw` fills, as floats 0..1, on a picture of w by h: GDI+'s smooth edges.
std::vector<float> coverage_of(int w, int h, const std::function<void(Graphics&)>& draw) {
    std::vector<float> out(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), 0.0f);
    Canvas c(w, h);
    if (!c.bits) return out;
    std::memset(c.bits, 0, static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 4);
    {
        auto bmp = c.surface();
        Graphics g(bmp.get());
        smooth(g);
        draw(g);
    }
    const std::uint32_t* px = pixels(c);
    for (std::size_t i = 0; i < out.size(); ++i) out[i] = static_cast<float>(px[i] >> 24) / 255.0f;
    return out;
}

// One premultiplied BGRA word over another (src over dst).
inline std::uint32_t over(std::uint32_t src, std::uint32_t dst) {
    const std::uint32_t a = src >> 24;
    // Opaque over anything, or anything over nothing: the source as it is; nothing over anything: what was there.
    if (a == 255 || dst == 0) return src;
    if (a == 0) return dst;
    const std::uint32_t keep = 255 - a;
    // Each channel of dst kept by 255 - a, rounded, and src added.
    auto ch = [&](int shift) {
        const std::uint32_t d = (dst >> shift) & 0xFF;
        const std::uint32_t s = (src >> shift) & 0xFF;
        return std::min<std::uint32_t>(255, s + (d * keep + 127) / 255) << shift;
    };
    return ch(24) | ch(16) | ch(8) | ch(0);
}

}  // namespace

// ---- the faces

bool load_fonts() {
    if (g_fonts_tried) return g_regular != nullptr;
    g_fonts_tried = true;
    // fonts\ beside the program, as the player's bundle lays it out (arm32/bundle_windows.sh): each file in its own
    // collection.
    const std::wstring folder = program_folder() + L"\\fonts\\";
    const wchar_t* files[4] = {L"Pretendard-Regular.ttf", L"Pretendard-SemiBold.ttf", L"Pretendard-Bold.ttf", L"DMTQWide-ExtraBold.ttf"};
    for (int i = 0; i < 4; ++i) {
        g_collections[i] = std::make_unique<PrivateFontCollection>();
        g_collections[i]->AddFontFile((folder + files[i]).c_str());
    }
    g_regular = family_of(L"Pretendard", g_collections[0].get());
    g_semibold = family_of(L"Pretendard SemiBold", g_collections[1].get());
    g_bold = family_of(L"Pretendard", g_collections[2].get());
    g_wide = family_of(L"DMTQ Wide", g_collections[3].get());
    return g_regular != nullptr;
}

std::unique_ptr<Font> font(Weight weight, float px, bool korean) {
    // Pretendard covers Hangul and Latin both: one face for either language, each weight its own file.
    const FontFamily* family = weight == Weight::kBold ? g_bold.get() : weight == Weight::kSemiBold ? g_semibold.get() : g_regular.get();
    if (family) {
        // The semibold family is regular in its own terms; the bold file's face is bold in Pretendard's.
        const INT style = weight == Weight::kBold ? FontStyleBold : FontStyleRegular;
        return std::make_unique<Font>(family, static_cast<REAL>(px), style, UnitPixel);
    }
    // Windows' own: semibold and bold both its bold.
    return std::make_unique<Font>(&windows_face(korean), static_cast<REAL>(px), weight == Weight::kRegular ? FontStyleRegular : FontStyleBold,
                                  UnitPixel);
}

std::unique_ptr<Font> wide_font(float px) {
    // DMTQ Wide's one face is its ExtraBold, regular in its own terms.
    if (g_wide) return std::make_unique<Font>(g_wide.get(), static_cast<REAL>(px), FontStyleRegular, UnitPixel);
    return std::make_unique<Font>(&windows_face(false), static_cast<REAL>(px), FontStyleBold, UnitPixel);
}

// ---- the frame behind a piece

bool backdrop_from(const std::vector<glass::Shot>& shots, const glass::Rect& r, int margin, Backdrop& out) {
    // The read that holds the rectangle whole.
    const glass::Shot* from = nullptr;
    for (const glass::Shot& s : shots) {
        if (r.x >= s.rect.x && r.y >= s.rect.y && r.x + r.w <= s.rect.x + s.rect.w && r.y + r.h <= s.rect.y + s.rect.h && s.w > 0 && s.h > 0) {
            from = &s;
            break;
        }
    }
    if (!from) return false;
    // The quarter pixels around it with the margin, on the window's multiples of 4 (a floor that rounds down below 0 too).
    auto down = [](int v) { return v >= 0 ? v / 4 : -((-v + 3) / 4); };
    const int qx0 = down(r.x - margin), qy0 = down(r.y - margin);
    const int qx1 = down(r.x + r.w + margin + 3), qy1 = down(r.y + r.h + margin + 3);
    out.x = qx0 * 4;
    out.y = qy0 * 4;
    out.w = std::max(1, qx1 - qx0);
    out.h = std::max(1, qy1 - qy0);
    out.rgb.resize(static_cast<std::size_t>(out.w) * static_cast<std::size_t>(out.h) * 3);
    // The read's own first quarter pixel, in the window's quarters.
    const int sx = from->rect.x / 4, sy = from->rect.y / 4;
    // What it is made from, hashed as it is copied (FNV-1a): its place, then its pixels.
    std::uint64_t hash = 1469598103934665603ull;
    auto mix = [&hash](std::uint64_t v) {
        hash ^= v;
        hash *= 1099511628211ull;
    };
    mix(static_cast<std::uint64_t>(static_cast<std::uint32_t>(out.x)) << 32 | static_cast<std::uint32_t>(out.y));
    mix(static_cast<std::uint64_t>(out.w) << 32 | static_cast<std::uint32_t>(out.h));
    for (int j = 0; j < out.h; ++j) {
        // The read's row for this one, its edge repeated past it.
        const int row = std::clamp(qy0 + j - sy, 0, from->h - 1);
        for (int i = 0; i < out.w; ++i) {
            const int col = std::clamp(qx0 + i - sx, 0, from->w - 1);
            const std::uint8_t* p = from->rgba.data() + (static_cast<std::size_t>(row) * static_cast<std::size_t>(from->w) + static_cast<std::size_t>(col)) * 4;
            std::uint8_t* q = out.rgb.data() + (static_cast<std::size_t>(j) * static_cast<std::size_t>(out.w) + static_cast<std::size_t>(i)) * 3;
            q[0] = p[0];
            q[1] = p[1];
            q[2] = p[2];
            mix(static_cast<std::uint64_t>(p[0]) | static_cast<std::uint64_t>(p[1]) << 8 | static_cast<std::uint64_t>(p[2]) << 16);
        }
    }
    out.hash = hash;
    return true;
}

void stamp(Backdrop& b, Canvas& picture, int x, int y) {
    if (!picture.bits || b.w <= 0 || b.h <= 0) return;
    const std::uint32_t* px = pixels(picture);
    for (int j = 0; j < b.h; ++j) {
        for (int i = 0; i < b.w; ++i) {
            // The 4 by 4 of the picture's pixels on this quarter pixel, averaged (premultiplied, so a plain mean).
            const int x0 = b.x + i * 4 - x, y0 = b.y + j * 4 - y;
            if (x0 + 4 <= 0 || y0 + 4 <= 0 || x0 >= picture.w || y0 >= picture.h) continue;
            std::uint32_t sum[4] = {0, 0, 0, 0};
            for (int dy = 0; dy < 4; ++dy) {
                for (int dx = 0; dx < 4; ++dx) {
                    const int sx = x0 + dx, sy = y0 + dy;
                    if (sx < 0 || sy < 0 || sx >= picture.w || sy >= picture.h) continue;
                    const std::uint32_t p = px[static_cast<std::size_t>(sy) * static_cast<std::size_t>(picture.w) + static_cast<std::size_t>(sx)];
                    sum[0] += p >> 24;
                    sum[1] += (p >> 16) & 0xFF;
                    sum[2] += (p >> 8) & 0xFF;
                    sum[3] += p & 0xFF;
                }
            }
            if (!sum[0]) continue;
            // Over the frame's colour there: the picture's colour, and the frame's through what it leaves.
            std::uint8_t* q = b.rgb.data() + (static_cast<std::size_t>(j) * static_cast<std::size_t>(b.w) + static_cast<std::size_t>(i)) * 3;
            const float keep = 1.0f - static_cast<float>(sum[0]) / (16.0f * 255.0f);
            for (int c = 0; c < 3; ++c) q[c] = static_cast<std::uint8_t>(std::clamp(static_cast<float>(sum[c + 1]) / 16.0f + q[c] * keep + 0.5f, 0.0f, 255.0f));
        }
    }
}

void soften(Backdrop& b, float sigma, float saturation, float dim) {
    if (b.w <= 0 || b.h <= 0) return;
    std::vector<float> v(b.rgb.begin(), b.rgb.end());
    // The blur at the backdrop's own pixels, four of the window's each.
    blur(v, b.w, b.h, 3, sigma / 4.0f);
    for (std::size_t i = 0; i + 2 < v.size(); i += 3) {
        // The colour pushed away from its grey (Rec. 709's weights), then darkened toward black.
        const float grey = 0.2126f * v[i] + 0.7152f * v[i + 1] + 0.0722f * v[i + 2];
        for (int c = 0; c < 3; ++c) {
            const float pushed = grey + (v[i + static_cast<std::size_t>(c)] - grey) * saturation;
            b.rgb[i + static_cast<std::size_t>(c)] = static_cast<std::uint8_t>(std::clamp(pushed * (1.0f - dim) + 0.5f, 0.0f, 255.0f));
        }
    }
}

// ---- a piece of glass

void smooth(Graphics& g) {
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    g.SetPixelOffsetMode(PixelOffsetModeHalf);
}

void rounded(GraphicsPath& path, RectF r, float radius) {
    if (radius <= 0) {
        path.AddRectangle(r);
        return;
    }
    // The corners' arcs no larger than the rectangle allows.
    const float d = std::min(radius * 2, std::min(r.Width, r.Height));
    path.AddArc(r.X, r.Y, d, d, 180, 90);
    path.AddArc(r.X + r.Width - d, r.Y, d, d, 270, 90);
    path.AddArc(r.X + r.Width - d, r.Y + r.Height - d, d, d, 0, 90);
    path.AddArc(r.X, r.Y + r.Height - d, d, d, 90, 90);
    path.CloseFigure();
}

void shape(Look& look, int w, int h, RectF r, float radius, bool beyond, float shadow, float blur_px, float drop) {
    // The same shape as last time: its coverage and shadow are as they were.
    const std::vector<float> key = {static_cast<float>(w), static_cast<float>(h), r.X, r.Y, r.Width, r.Height, radius, beyond ? 1.0f : 0.0f, shadow, blur_px, drop};
    if (look.made_for == key && look.cover.size() == static_cast<std::size_t>(w) * static_cast<std::size_t>(h)) {
        look.top = r.Y;
        look.height = r.Height;
        return;
    }
    look.made_for = key;
    look.w = w;
    look.h = h;
    const auto fill = [&](Graphics& g, RectF at) {
        GraphicsPath path;
        rounded(path, at, radius);
        SolidBrush white(Color(255, 255, 255, 255));
        g.FillPath(&white, &path);
    };
    // The glass's coverage: the shape on the window's pixels, smooth at its edges.
    const std::vector<float> cover = coverage_of(w, h, [&](Graphics& g) { fill(g, r); });
    look.cover.resize(cover.size());
    for (std::size_t i = 0; i < cover.size(); ++i) look.cover[i] = static_cast<std::uint8_t>(std::lround(cover[i] * 255.0f));
    // The shadow: the shape moved down, blurred (a CSS blur is twice its Gaussian's sigma), on a picture larger by the
    // blur's reach on every side so that its edges blur as if the window went on; a shape that goes past the window (the
    // bar's) goes past that picture too.
    const float sigma = blur_px / 2.0f;
    const int reach = static_cast<int>(std::ceil(3.0f * sigma + std::fabs(drop))) + 1;
    const int bw = w + 2 * reach, bh = h + 2 * reach;
    RectF moved(r.X + static_cast<float>(reach), r.Y + static_cast<float>(reach) + drop, r.Width, r.Height);
    if (beyond) {
        // Past the larger picture's sides and top as well.
        moved.X -= static_cast<float>(reach);
        moved.Width += static_cast<float>(2 * reach);
        moved.Height += moved.Y;
        moved.Y = 0;
    }
    std::vector<float> dark = coverage_of(bw, bh, [&](Graphics& g) { fill(g, moved); });
    blur(dark, bw, bh, 1, sigma);
    look.shade.assign(static_cast<std::size_t>(w) * static_cast<std::size_t>(h), 0);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const float a = dark[static_cast<std::size_t>(y + reach) * static_cast<std::size_t>(bw) + static_cast<std::size_t>(x + reach)] * shadow;
            look.shade[static_cast<std::size_t>(y) * static_cast<std::size_t>(w) + static_cast<std::size_t>(x)] =
                static_cast<std::uint8_t>(std::clamp(std::lround(a * 255.0f), 0L, 255L));
        }
    }
    // The light layer over the glass's own height.
    look.top = r.Y;
    look.height = r.Height;
}

void compose(Canvas& out, int ox, int oy, const Look& look, const Backdrop* b, int x, int y) {
    // The look within the picture, whole.
    if (!out.bits || ox < 0 || oy < 0 || ox + look.w > out.w || oy + look.h > out.h || !look.fore || !look.fore->bits) return;
    const int w = look.w, h = look.h;
    std::uint32_t* dst = pixels(out);
    const std::uint32_t* fore = pixels(*look.fore);
    const auto& grain = noise();
    // The glass's colour over the window's pixels, in sixteenths of a byte: from the frame behind (its quarter pixels
    // tinted and lit, then spread over the window's), or the bare tint.
    std::vector<std::int32_t> row0, row1, glass_row(static_cast<std::size_t>(w) * 3);
    // The tint and light at each of the frame's quarter pixels, then the glass's colour there.
    std::vector<std::int32_t> grid;
    std::vector<int> col_at(static_cast<std::size_t>(w));
    std::vector<int> col_frac(static_cast<std::size_t>(w));
    float bare_alpha = 1.0f;
    if (b && b->w > 0 && b->h > 0) {
        // Each window column's place among the frame's quarter pixels: the left one and how far toward the next (of 256).
        for (int i = 0; i < w; ++i) {
            const float u = (static_cast<float>(x + i) + 0.5f - static_cast<float>(b->x)) / 4.0f - 0.5f;
            const float fu = std::floor(u);
            col_at[static_cast<std::size_t>(i)] = std::clamp(static_cast<int>(fu), 0, b->w - 1);
            col_frac[static_cast<std::size_t>(i)] = static_cast<int>(fu) < 0 || static_cast<int>(fu) >= b->w - 1 ? 0 : static_cast<int>((u - fu) * 256.0f);
        }
        // The tint each quarter pixel needs: the piece's own, deeper where words sit over a light frame. A zone's tint is
        // the deepest any of its pixels needs (even under the whole line), and it fades out beyond the words.
        std::vector<float> zone_tint(look.zones.size(), look.tint);
        for (std::size_t z = 0; z < look.zones.size(); ++z) {
            const Look::Zone& zone = look.zones[z];
            for (int j = 0; j < b->h; ++j) {
                // The quarter pixel's middle in the window's pixels.
                const float wy = static_cast<float>(b->y + j * 4 + 2 - y);
                if (wy < zone.y0 - 2 || wy > zone.y1 + 2) continue;
                const float light = light_at(look, wy);
                float tint[3];
                tint_at(look, wy, tint);
                for (int i = 0; i < b->w; ++i) {
                    const float wx = static_cast<float>(b->x + i * 4 + 2 - x);
                    if (wx < zone.x0 - 2 || wx > zone.x1 + 2) continue;
                    const std::uint8_t* p = b->rgb.data() + (static_cast<std::size_t>(j) * static_cast<std::size_t>(b->w) + static_cast<std::size_t>(i)) * 3;
                    const float rgb[3] = {static_cast<float>(p[0]), static_cast<float>(p[1]), static_cast<float>(p[2])};
                    zone_tint[z] = std::max(zone_tint[z], tint_for(rgb, tint, look.tint, light, zone.under));
                }
            }
        }
        grid.resize(static_cast<std::size_t>(b->w) * static_cast<std::size_t>(b->h) * 3);
        for (int j = 0; j < b->h; ++j) {
            const float wy = static_cast<float>(b->y + j * 4 + 2 - y);
            const float light = light_at(look, wy);
            float tint[3];
            tint_at(look, wy, tint);
            for (int i = 0; i < b->w; ++i) {
                const float wx = static_cast<float>(b->x + i * 4 + 2 - x);
                float a = look.tint;
                for (std::size_t z = 0; z < look.zones.size(); ++z) {
                    const Look::Zone& zone = look.zones[z];
                    // How far outside the words' box, and the deeper tint fading out over the feather.
                    const float dx = std::max({zone.x0 - wx, 0.0f, wx - zone.x1}), dy = std::max({zone.y0 - wy, 0.0f, wy - zone.y1});
                    const float k = std::clamp(1.0f - std::sqrt(dx * dx + dy * dy) / std::max(1.0f, look.feather), 0.0f, 1.0f);
                    // Eased, so that the fade has no edge of its own.
                    const float eased = k * k * (3 - 2 * k);
                    a = std::max(a, look.tint + (zone_tint[z] - look.tint) * eased);
                }
                const std::uint8_t* p = b->rgb.data() + (static_cast<std::size_t>(j) * static_cast<std::size_t>(b->w) + static_cast<std::size_t>(i)) * 3;
                for (int c = 0; c < 3; ++c) {
                    const float tinted = static_cast<float>(p[c]) * (1 - a) + tint[c] * a;
                    const float lit = tinted * (1 - light) + 255.0f * light;
                    grid[(static_cast<std::size_t>(j) * static_cast<std::size_t>(b->w) + static_cast<std::size_t>(i)) * 3 + static_cast<std::size_t>(c)] =
                        static_cast<std::int32_t>(lit * 16.0f + 0.5f);
                }
            }
        }
        row0.resize(static_cast<std::size_t>(w) * 3);
        row1.resize(static_cast<std::size_t>(w) * 3);
    } else {
        // No frame behind: the bare tint, which lets the game through a little, unblurred.
        bare_alpha = kTintBare;
    }
    // A grid row spread across the window's columns.
    auto spread = [&](int j, std::vector<std::int32_t>& into) {
        const std::int32_t* g = grid.data() + static_cast<std::size_t>(std::clamp(j, 0, b->h - 1)) * static_cast<std::size_t>(b->w) * 3;
        for (int i = 0; i < w; ++i) {
            const int at = col_at[static_cast<std::size_t>(i)], f = col_frac[static_cast<std::size_t>(i)];
            const std::int32_t* p = g + static_cast<std::size_t>(at) * 3;
            const std::int32_t* q = g + static_cast<std::size_t>(std::min(at + 1, b->w - 1)) * 3;
            for (int c = 0; c < 3; ++c) into[static_cast<std::size_t>(i) * 3 + static_cast<std::size_t>(c)] = (p[c] * (256 - f) + q[c] * f) >> 8;
        }
    };
    int have0 = -2, have1 = -2;
    for (int row = 0; row < h; ++row) {
        const std::size_t base = static_cast<std::size_t>(row) * static_cast<std::size_t>(w);
        // The same row of the picture, where the look's goes.
        std::uint32_t* out_row = dst + static_cast<std::size_t>(oy + row) * static_cast<std::size_t>(out.w) + static_cast<std::size_t>(ox);
        // The glass's colour along this row, in sixteenths.
        if (b && b->w > 0) {
            const float v = (static_cast<float>(y + row) + 0.5f - static_cast<float>(b->y)) / 4.0f - 0.5f;
            const float fv = std::floor(v);
            const int j0 = static_cast<int>(fv);
            const int f = j0 < 0 || j0 >= b->h - 1 ? 0 : static_cast<int>((v - fv) * 256.0f);
            // The two grid rows around it, spread once each as the rows go down.
            if (have0 != j0) {
                if (have1 == j0) {
                    std::swap(row0, row1);
                } else {
                    spread(j0, row0);
                }
                have0 = j0;
                spread(j0 + 1, row1);
                have1 = j0 + 1;
            }
            for (std::size_t k = 0; k < glass_row.size(); ++k) glass_row[k] = (row0[k] * (256 - f) + row1[k] * f) >> 8;
        } else {
            // The bare tint with the light layer.
            const float light = light_at(look, static_cast<float>(row) + 0.5f);
            float tint[3];
            tint_at(look, static_cast<float>(row) + 0.5f, tint);
            for (int i = 0; i < w; ++i) {
                for (int c = 0; c < 3; ++c) {
                    glass_row[static_cast<std::size_t>(i) * 3 + static_cast<std::size_t>(c)] =
                        static_cast<std::int32_t>(tint[c] * 16.0f * (1 - light) + 255.0f * 16.0f * light);
                }
            }
        }
        const std::uint8_t* grain_row = grain.data() + static_cast<std::size_t>((y + row) & 63) * 64;
        for (int i = 0; i < w; ++i) {
            const std::size_t at = base + static_cast<std::size_t>(i);
            const std::uint32_t cov = look.cover[at], dark = look.shade[at];
            // The shadow: black at its alpha (the glass over it hides it where it covers it whole).
            std::uint32_t px = dark << 24;
            if (cov) {
                // The glass's colour with the noise (2 % of a grey from the tile), in bytes.
                const int n = grain_row[(x + i) & 63];
                std::uint32_t rgb[3];
                for (int c = 0; c < 3; ++c) {
                    const int v16 = (glass_row[static_cast<std::size_t>(i) * 3 + static_cast<std::size_t>(c)] * 251 + n * 16 * 5) >> 8;
                    rgb[c] = static_cast<std::uint32_t>(std::clamp((v16 + 8) >> 4, 0, 255));
                }
                // Its coverage: whole inside, smooth at the edge; over no frame, the bare tint's alpha.
                const std::uint32_t a = static_cast<std::uint32_t>(static_cast<float>(cov) * bare_alpha + 0.5f);
                const std::uint32_t glass = a << 24 | (rgb[0] * a / 255) << 16 | (rgb[1] * a / 255) << 8 | (rgb[2] * a / 255);
                px = over(glass, px);
            }
            // What the window held under it (the question's dimmed game), then what is drawn on the glass over it all.
            px = over(px, out_row[i]);
            out_row[i] = over(fore[at], px);
        }
    }
}

void backdrop_fill(Canvas& out, const Backdrop* b, float bare) {
    if (!out.bits) return;
    std::uint32_t* dst = pixels(out);
    const int w = out.w, h = out.h;
    if (!b || b->w <= 0 || b->h <= 0) {
        // No frame: the game through a plain dim.
        const auto a = static_cast<std::uint32_t>(std::lround(bare * 255.0f));
        std::fill(dst, dst + static_cast<std::size_t>(w) * static_cast<std::size_t>(h), a << 24);
        return;
    }
    // Each column's place among the frame's quarter pixels, as compose() spreads them.
    std::vector<int> at(static_cast<std::size_t>(w)), frac(static_cast<std::size_t>(w));
    for (int i = 0; i < w; ++i) {
        const float u = (static_cast<float>(i) + 0.5f - static_cast<float>(b->x)) / 4.0f - 0.5f;
        const float fu = std::floor(u);
        at[static_cast<std::size_t>(i)] = std::clamp(static_cast<int>(fu), 0, b->w - 1);
        frac[static_cast<std::size_t>(i)] = static_cast<int>(fu) < 0 || static_cast<int>(fu) >= b->w - 1 ? 0 : static_cast<int>((u - fu) * 256.0f);
    }
    std::vector<std::int32_t> r0(static_cast<std::size_t>(w) * 3), r1(static_cast<std::size_t>(w) * 3);
    auto spread = [&](int j, std::vector<std::int32_t>& into) {
        const std::uint8_t* g = b->rgb.data() + static_cast<std::size_t>(std::clamp(j, 0, b->h - 1)) * static_cast<std::size_t>(b->w) * 3;
        for (int i = 0; i < w; ++i) {
            const std::uint8_t* p = g + static_cast<std::size_t>(at[static_cast<std::size_t>(i)]) * 3;
            const std::uint8_t* q = g + static_cast<std::size_t>(std::min(at[static_cast<std::size_t>(i)] + 1, b->w - 1)) * 3;
            const int f = frac[static_cast<std::size_t>(i)];
            // In sixteenths, as the glass's rows.
            for (int c = 0; c < 3; ++c) into[static_cast<std::size_t>(i) * 3 + static_cast<std::size_t>(c)] = (p[c] * 16 * (256 - f) + q[c] * 16 * f) >> 8;
        }
    };
    const auto& grain = noise();
    int have = -2;
    for (int row = 0; row < h; ++row) {
        const float v = (static_cast<float>(row) + 0.5f - static_cast<float>(b->y)) / 4.0f - 0.5f;
        const float fv = std::floor(v);
        const int j0 = static_cast<int>(fv);
        const int f = j0 < 0 || j0 >= b->h - 1 ? 0 : static_cast<int>((v - fv) * 256.0f);
        if (have != j0) {
            spread(j0, r0);
            spread(j0 + 1, r1);
            have = j0;
        }
        const std::uint8_t* grain_row = grain.data() + static_cast<std::size_t>(row & 63) * 64;
        std::uint32_t* line = dst + static_cast<std::size_t>(row) * static_cast<std::size_t>(w);
        for (int i = 0; i < w; ++i) {
            std::uint32_t rgb[3];
            const int n = grain_row[i & 63];
            for (int c = 0; c < 3; ++c) {
                const std::size_t k = static_cast<std::size_t>(i) * 3 + static_cast<std::size_t>(c);
                // The same faint noise as the glass: a smooth dim has the same banding to hide.
                const int v16 = (((r0[k] * (256 - f) + r1[k] * f) >> 8) * 251 + n * 16 * 5) >> 8;
                rgb[c] = static_cast<std::uint32_t>(std::clamp((v16 + 8) >> 4, 0, 255));
            }
            // Opaque: the dimmed, blurred game in place of the game.
            line[i] = 0xFF000000u | rgb[0] << 16 | rgb[1] << 8 | rgb[2];
        }
    }
}

// ---- drawing on a piece

void glow(Canvas& c, RectF bounds, float sigma, float dx, float dy, const Color& colour, const std::function<void(Graphics&)>& draw) {
    if (!c.bits) return;
    // The part of the canvas worked on: the bounds, the blur's reach and the move around them, within the canvas.
    const int reach = static_cast<int>(std::ceil(3.0f * sigma + std::max(std::fabs(dx), std::fabs(dy)))) + 2;
    const int x0 = std::max(0, static_cast<int>(std::floor(bounds.X)) - reach), y0 = std::max(0, static_cast<int>(std::floor(bounds.Y)) - reach);
    const int x1 = std::min(c.w, static_cast<int>(std::ceil(bounds.X + bounds.Width)) + reach);
    const int y1 = std::min(c.h, static_cast<int>(std::ceil(bounds.Y + bounds.Height)) + reach);
    if (x1 <= x0 || y1 <= y0) return;
    const int w = x1 - x0, h = y1 - y0;
    // What it fills, drawn in the canvas's own pixels on a picture of the part alone.
    std::vector<float> a = coverage_of(w, h, [&](Graphics& g) {
        g.TranslateTransform(static_cast<REAL>(-x0), static_cast<REAL>(-y0));
        draw(g);
    });
    blur(a, w, h, 1, sigma);
    std::uint32_t* px = pixels(c);
    const float strength = static_cast<float>(colour.GetA()) / 255.0f;
    // Moved by whole pixels: a glow is soft enough for that.
    const int mx = static_cast<int>(std::lround(dx)), my = static_cast<int>(std::lround(dy));
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const int sx = x - mx, sy = y - my;
            if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
            const float k = a[static_cast<std::size_t>(sy) * static_cast<std::size_t>(w) + static_cast<std::size_t>(sx)] * strength;
            if (k <= 0.002f) continue;
            const auto alpha = static_cast<std::uint32_t>(std::lround(k * 255.0f));
            const std::uint32_t under = alpha << 24 | (colour.GetR() * alpha / 255) << 16 | (colour.GetG() * alpha / 255) << 8 | (colour.GetB() * alpha / 255);
            std::uint32_t& d = px[static_cast<std::size_t>(y + y0) * static_cast<std::size_t>(c.w) + static_cast<std::size_t>(x + x0)];
            // Under what the canvas holds already.
            d = over(d, under);
        }
    }
}

}  // namespace player::overlay
