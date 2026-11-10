// What the player's own windows drawn with GDI+ share: the overlay over the game (overlay_win32.cpp) and the error box
// before it (error_box_win32.cpp). GDI+ itself with the headers it needs, a picture it draws into (Canvas), the text's
// settings, the face, and UTF-8 as Windows' UTF-16.
#pragma once

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

#include <memory>
#include <string>

namespace player::overlay {

// A window's picture: a 32-bit premultiplied DIB that GDI+ draws into, shown by UpdateLayeredWindow for a layered window
// or copied by BitBlt from its DC for another. `bits` is null when Windows could not make it.
struct Canvas {
    HDC dc = nullptr;
    HBITMAP bitmap = nullptr;
    HGDIOBJ old = nullptr;
    void* bits = nullptr;
    int w = 0, h = 0;
    Canvas(int width, int height) : w(width), h(height) {
        // Top-down rows (a negative height), four bytes a pixel.
        BITMAPINFO info{};
        info.bmiHeader.biSize = sizeof info.bmiHeader;
        info.bmiHeader.biWidth = w;
        info.bmiHeader.biHeight = -h;
        info.bmiHeader.biPlanes = 1;
        info.bmiHeader.biBitCount = 32;
        // A DC of its own with the DIB in it, for UpdateLayeredWindow and BitBlt.
        dc = CreateCompatibleDC(nullptr);
        bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
        old = SelectObject(dc, bitmap);
    }
    ~Canvas() {
        // The DC's own bitmap back in it before both go.
        SelectObject(dc, old);
        DeleteObject(bitmap);
        DeleteDC(dc);
    }
    Canvas(const Canvas&) = delete;
    Canvas& operator=(const Canvas&) = delete;
    // GDI+ over the same pixels, smooth shapes and text.
    std::unique_ptr<Gdiplus::Bitmap> surface() {
        return std::make_unique<Gdiplus::Bitmap>(w, h, w * 4, PixelFormat32bppPARGB, static_cast<BYTE*>(bits));
    }
    // Shown at (x, y) on the screen, at `alpha` as a whole: a layered window's picture.
    void show(HWND window, int x, int y, BYTE alpha) {
        POINT at{x, y}, from{0, 0};
        SIZE size{w, h};
        BLENDFUNCTION blend{AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA};
        UpdateLayeredWindow(window, nullptr, &at, &size, dc, &from, 0, &blend, ULW_ALPHA);
    }
};

// Smooth edges and text, pixels at their centres.
inline void text_setup(Gdiplus::Graphics& g) {
    g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
    g.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAliasGridFit);
    g.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHalf);
}

// The face: Windows' own for Korean, else its UI face; whatever sans face there is where neither is (Wine).
inline std::unique_ptr<Gdiplus::FontFamily> face(bool korean) {
    for (const wchar_t* name : {korean ? L"Malgun Gothic" : L"Segoe UI", L"Malgun Gothic", L"Segoe UI"}) {
        auto family = std::make_unique<Gdiplus::FontFamily>(name);
        if (family->IsAvailable()) return family;
    }
    return std::unique_ptr<Gdiplus::FontFamily>(Gdiplus::FontFamily::GenericSansSerif()->Clone());
}

// UTF-8 as UTF-16, as Windows' text calls take it.
inline std::wstring wide(const std::string& s) {
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

}  // namespace player::overlay
