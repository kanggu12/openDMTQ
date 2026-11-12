// The faces the overlay over the game draws its words in (overlay_glass.cpp), as the player loads them from fonts\ beside
// the program (the build puts them there, as the player's bundle does): Pretendard in each weight the overlay uses, for
// English and for Korean alike, and DMTQ Wide for the bar's name; and the words of both languages drawn in them, every
// Hangul syllable of the question before quitting a glyph of Pretendard's own, not the box a face without Hangul draws.
// Under Wine as on Windows: Wine's GDI+ found no family by its name in the player's own collection, and the overlay fell
// back to a face of Wine's with no Hangul (its Korean showed as boxes). Prints ALL CHECKS PASSED when every check held.
#include "overlay_glass.h"

#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace {

int g_checks = 0, g_failed = 0;

// One check, said only when it fails.
void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) {
        ++g_failed;
        std::printf("FAIL %s\n", what);
    }
}

using player::overlay::Weight;

// The pixels of one character drawn in a font, black on white, on a picture large enough for any glyph of its size.
std::vector<std::uint32_t> drawn(wchar_t c, const Gdiplus::Font& font) {
    Gdiplus::Bitmap picture(64, 64, PixelFormat32bppARGB);
    {
        Gdiplus::Graphics g(&picture);
        g.Clear(Gdiplus::Color(255, 255, 255, 255));
        g.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAliasGridFit);
        Gdiplus::SolidBrush ink(Gdiplus::Color(255, 0, 0, 0));
        const wchar_t text[2] = {c, 0};
        g.DrawString(text, 1, &font, Gdiplus::PointF(8, 8), &ink);
    }
    std::vector<std::uint32_t> out(64 * 64);
    Gdiplus::BitmapData data{};
    Gdiplus::Rect all(0, 0, 64, 64);
    if (picture.LockBits(&all, Gdiplus::ImageLockModeRead, PixelFormat32bppARGB, &data) == Gdiplus::Ok) {
        // Row by row: the picture's rows may be farther apart than its width.
        for (int y = 0; y < 64; ++y) std::memcpy(&out[static_cast<std::size_t>(y) * 64], static_cast<const char*>(data.Scan0) + y * data.Stride, 64 * 4);
        picture.UnlockBits(&data);
    }
    return out;
}

// How many of a picture's pixels are not white: its ink.
int ink(const std::vector<std::uint32_t>& pixels) {
    int n = 0;
    for (std::uint32_t p : pixels) n += (p & 0xFFFFFF) != 0xFFFFFF;
    return n;
}

// A face as its font file has it, for what the overlay draws to be held to: the file in a collection of its own and the
// one family it lists. Both live as long as the program, as the overlay's own do.
const Gdiplus::FontFamily* file_face(const wchar_t* file) {
    static std::vector<std::unique_ptr<Gdiplus::PrivateFontCollection>> collections;
    static std::vector<std::unique_ptr<Gdiplus::FontFamily>> families;
    // The program's own folder, as the overlay's: fonts\ beside it.
    wchar_t self[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    std::wstring path(self);
    path = path.substr(0, path.find_last_of(L"\\/") + 1) + L"fonts\\" + file;
    collections.push_back(std::make_unique<Gdiplus::PrivateFontCollection>());
    collections.back()->AddFontFile(path.c_str());
    families.push_back(std::make_unique<Gdiplus::FontFamily>());
    INT found = 0;
    if (collections.back()->GetFamilies(1, families.back().get(), &found) != Gdiplus::Ok || found < 1) return nullptr;
    return families.back().get();
}

// Whether a line drawn in two fonts gives the same pixels, a character at a time.
bool same(const std::wstring& line, const Gdiplus::Font& a, const Gdiplus::Font& b) {
    for (const wchar_t c : line) {
        if (drawn(c, a) != drawn(c, b)) return false;
    }
    return true;
}

}  // namespace

int main() {
    // GDI+ up for the program's life, as in the player: the faces loaded here are let go of only as the program ends, and
    // GDI+'s objects must all be gone before it is shut down.
    Gdiplus::GdiplusStartupInput input;
    ULONG_PTR token = 0;
    Gdiplus::GdiplusStartup(&token, &input, nullptr);
    {
        // The faces, as the overlay loads them when it starts.
        check(player::overlay::load_fonts(), "Pretendard is loaded from fonts beside the program");
        // Each weight the overlay draws in, for either language: Pretendard's own family, never Windows' or Wine's face.
        check(player::overlay::words_face(Weight::kRegular, false) == "Pretendard" && player::overlay::words_face(Weight::kRegular, true) == "Pretendard",
              "the regular words, English and Korean, are drawn in Pretendard");
        check(player::overlay::words_face(Weight::kSemiBold, false) == "Pretendard SemiBold" &&
                  player::overlay::words_face(Weight::kSemiBold, true) == "Pretendard SemiBold",
              "the semibold words, English and Korean, are drawn in Pretendard SemiBold");
        check(player::overlay::words_face(Weight::kBold, false) == "Pretendard" && player::overlay::words_face(Weight::kBold, true) == "Pretendard",
              "the bold words, English and Korean, are drawn in Pretendard's bold");
        // The words of the question before quitting, in both languages.
        const std::wstring words[] = {L"게임을 끝낼까요?", L"곡 도중에 끝내면 기록이 남지 않아요.", L"계속하기", L"게임 끝내기", L"Quit the game?",
                                      L"Quitting mid-song loses the song's record.", L"Keep playing"};
        // The fonts the overlay makes, in each weight and for either language, draw them as Pretendard's own files do: the
        // regular and the semibold as their faces are, the bold file's face in bold, as the overlay asks for it. (Read
        // back by its pixels: a family read back from a font (Font::GetFamily) frees the font's own on Windows.)
        {
            const Gdiplus::FontFamily* regular = file_face(L"Pretendard-Regular.ttf");
            const Gdiplus::FontFamily* semibold = file_face(L"Pretendard-SemiBold.ttf");
            const Gdiplus::FontFamily* bold = file_face(L"Pretendard-Bold.ttf");
            bool drawn_as_file = regular && semibold && bold;
            for (const Weight weight : {Weight::kRegular, Weight::kSemiBold, Weight::kBold}) {
                if (!drawn_as_file) break;
                const Gdiplus::FontFamily* family = weight == Weight::kBold ? bold : weight == Weight::kSemiBold ? semibold : regular;
                const Gdiplus::Font file(family, 24, weight == Weight::kBold ? Gdiplus::FontStyleBold : Gdiplus::FontStyleRegular, Gdiplus::UnitPixel);
                for (const std::wstring& line : words) {
                    drawn_as_file = drawn_as_file && same(line, *player::overlay::font(weight, 24, false), file) &&
                                    same(line, *player::overlay::font(weight, 24, true), file);
                }
            }
            check(drawn_as_file, "every font the overlay makes, in each weight and for either language, draws the question as Pretendard's files do");
        }
        // The bar's name where its pictures are not there, as DMTQ Wide's file draws it.
        {
            const Gdiplus::FontFamily* wide = file_face(L"DMTQWide-ExtraBold.ttf");
            check(wide && same(L"OPEN DMTQ", *player::overlay::wide_font(15), Gdiplus::Font(wide, 15, Gdiplus::FontStyleRegular, Gdiplus::UnitPixel)),
                  "the bar's name in words is drawn as DMTQ Wide's file draws it");
        }
        // The words themselves, each character drawn in each weight, against a character no face of the player's has (a
        // private use one): a face without Hangul draws every syllable as that same box (or blank), Pretendard each as its
        // own glyph, with ink.
        bool hangul = true, latin = true;
        for (const Weight weight : {Weight::kRegular, Weight::kSemiBold, Weight::kBold}) {
            for (const std::wstring& line : words) {
                const bool korean = line[0] >= 0xAC00;
                const auto font = player::overlay::font(weight, 24, korean);
                const std::vector<std::uint32_t> none = drawn(0xE000, *font);
                for (const wchar_t c : line) {
                    // Spaces and marks have no ink to tell apart.
                    if (c == L' ' || c == L'?' || c == L'.' || c == L'\'' || c == L'-') continue;
                    const std::vector<std::uint32_t> glyph = drawn(c, *font);
                    const bool own = ink(glyph) > 0 && glyph != none;
                    if (c >= 0xAC00 && c <= 0xD7A3) hangul = hangul && own;
                    else latin = latin && own;
                }
            }
        }
        check(hangul, "every Hangul syllable of the question is drawn as a glyph of its own, in each weight");
        check(latin, "every letter of its English is drawn as a glyph of its own, in each weight");
    }
    if (g_failed) {
        std::printf("%d of %d checks FAILED\n", g_failed, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
