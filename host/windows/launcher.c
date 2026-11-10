/*
 * OpenDMTQ.exe, the Windows bundle's launcher: runs the bundle's own Python with the host program
 * (app\host\opendmtq_host) in this console window, passes on whatever it was given (a command, or the folder a person
 * dropped on it), and ends with its exit status. The host program does all the work; this only has to find it.
 *
 * Built on Linux with MinGW-w64 (host/windows/build.sh), linked statically, so that it needs nothing but Windows.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <math.h>
#include <stdio.h>
#include <wchar.h>

/* What to do about any of them, in both languages. The Korean one breaks its line itself: GDI would break it inside a
   word. */
#define UNPACK_EN L"Unpack the whole zip again, into a folder of its own, and start OpenDMTQ.exe from there."
#define UNPACK_KO L"zip 전체를 새 폴더에 다시 풀고,\n그 안의 OpenDMTQ.exe로 시작하세요."

/* Room for long folder names (Windows allows paths beyond MAX_PATH with long path support on). */
#define PATH_ROOM 4096

/* The rest of this program's command line, after its own name (quoted or not) and the spaces after it. */
static const wchar_t *arguments(void)
{
    const wchar_t *cmd = GetCommandLineW();
    if (*cmd == L'"') {
        /* A quoted name ends at the next quote. */
        cmd++;
        while (*cmd && *cmd != L'"') {
            cmd++;
        }
        if (*cmd) {
            cmd++;
        }
    } else {
        /* An unquoted one at the first space or tab. */
        while (*cmd && *cmd != L' ' && *cmd != L'\t') {
            cmd++;
        }
    }
    while (*cmd == L' ' || *cmd == L'\t') {
        cmd++;
    }
    return cmd;
}

/* ---- What went wrong before there is a program to say it (the window may close at once): the PC client's dialog
   (client/opendmtq_client/dialogs.py) in a window of its own, drawn here with GDI as the player's is with GDI+. */

typedef struct {
    BYTE r, g, b;
} Rgb;

/* The PC client's look (client/opendmtq_client/theme.py and art.py). */
static const Rgb FIELD = {0x11, 0x15, 0x1a}, PANEL = {0x1a, 0x1f, 0x25}, CHALK = {0xee, 0xf2, 0xf6},
                 ASH = {0xae, 0xb8, 0xc3}, BAD = {0xff, 0x5f, 0x72}, CYAN = {0x6f, 0xd6, 0xff}, INK = {0x0d, 0x1c, 0x04},
                 WHITE = {0xff, 0xff, 0xff}, BLACK = {0, 0, 0};
/* The lit button's three colours down it: as it is, under the pointer, pressed (art.BUTTON_LOOKS["home"]). */
static const Rgb LIT[3][3] = {{{0xac, 0xf6, 0x73}, {0x8c, 0xf2, 0x3d}, {0x76, 0xcb, 0x33}},
                              {{0xbc, 0xf9, 0x8c}, {0x9d, 0xf5, 0x5a}, {0x82, 0xd8, 0x3c}},
                              {{0x9e, 0xe6, 0x65}, {0x7f, 0xe2, 0x34}, {0x6b, 0xb9, 0x2e}}};
/* The site's shards at the page's edges (art.FACETS): opacity, the number of points, the points in a 1440 x 900 page. */
static const struct {
    double opacity;
    int n;
    double p[4][2];
} FACETS[] = {
    {0.75, 3, {{1440, 60}, {1330, 0}, {1440, 0}}},
    {0.62, 4, {{1290, 70}, {1440, 250}, {1440, 420}, {1345, 300}}},
    {0.34, 4, {{1345, 300}, {1440, 420}, {1440, 670}, {1400, 480}}},
    {0.72, 3, {{0, 250}, {112, 470}, {0, 425}}},
    {0.30, 4, {{0, 425}, {112, 470}, {176, 900}, {0, 900}}},
    {0.16, 4, {{1400, 480}, {1440, 670}, {1440, 900}, {1344, 900}}},
};

static struct {
    const wchar_t *message, *detail, *ok;
    double s;                       /* Windows' scale: 1 at 96 dpi */
    int w, h;                       /* the window's inside */
    double cx, cy, cw, ch;          /* the card */
    double bx, by, bw, bh;          /* its button */
    int state, done;                /* the button: 0 as it is, 1 under the pointer, 2 pressed; the box answered */
    HFONT title, body, bold;
    HDC dc;
    HBITMAP bitmap;
    HGDIOBJ old;
    DWORD *bits;
    HWND window;
} box;

/* One pixel of the picture mixed toward a colour by `a` (0 to 1). */
static void blend(int x, int y, Rgb c, double a)
{
    if (x < 0 || y < 0 || x >= box.w || y >= box.h || a <= 0) {
        return;
    }
    if (a > 1) {
        a = 1;
    }
    DWORD *p = box.bits + (size_t)y * (size_t)box.w + (size_t)x;
    const double r = (*p >> 16) & 0xff, g = (*p >> 8) & 0xff, b = *p & 0xff;
    *p = 0xff000000u | ((DWORD)(r + (c.r - r) * a + 0.5) << 16) | ((DWORD)(g + (c.g - g) * a + 0.5) << 8) |
         (DWORD)(b + (c.b - b) * a + 0.5);
}

/* Shapes, asked of a point: the card (its top-right corner cut), the button (its top-left and bottom-right cut). */
static int in_card(double x, double y, double X, double Y, double W, double H, double cut)
{
    return x >= X && x < X + W && y >= Y && y < Y + H && (x - (X + W - cut)) <= (y - Y);
}
static int in_button(double x, double y, double X, double Y, double W, double H, double cut)
{
    return x >= X && x < X + W && y >= Y && y < Y + H && (x - X) + (y - Y) >= cut &&
           (X + W - x) + (Y + H - y) >= cut;
}
static int in_polygon(double x, double y, const double (*p)[2], int n)
{
    int inside = 0;
    for (int i = 0, j = n - 1; i < n; j = i++) {
        if (((p[i][1] > y) != (p[j][1] > y)) && (x < (p[j][0] - p[i][0]) * (y - p[i][1]) / (p[j][1] - p[i][1]) + p[i][0])) {
            inside = !inside;
        }
    }
    return inside;
}

/* How much of a pixel a card or a button covers (4 x 4 samples): smooth edges where they run at 45 degrees. */
static double card_cover(int px, int py, double X, double Y, double W, double H, double cut)
{
    int n = 0;
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            n += in_card(px + (i + 0.5) / 4, py + (j + 0.5) / 4, X, Y, W, H, cut);
        }
    }
    return n / 16.0;
}
static double button_cover(int px, int py, double X, double Y, double W, double H, double cut)
{
    int n = 0;
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            n += in_button(px + (i + 0.5) / 4, py + (j + 0.5) / 4, X, Y, W, H, cut);
        }
    }
    return n / 16.0;
}

/* Text in a box, in a font and a colour, wrapped at its words; its height when `measure`. */
static int text(const wchar_t *what, HFONT font, Rgb colour, RECT r, UINT how, int measure)
{
    HGDIOBJ before = SelectObject(box.dc, font);
    SetBkMode(box.dc, TRANSPARENT);
    SetTextColor(box.dc, RGB(colour.r, colour.g, colour.b));
    const int h = DrawTextW(box.dc, what, -1, &r, how | DT_NOPREFIX | (measure ? DT_CALCRECT : 0));
    SelectObject(box.dc, before);
    return h;
}

/* The window's picture: the page behind, the card on its shadow with the lamp, the question and what it means, and
   the lit button with the keyboard's ring. */
static void draw(void)
{
    const double s = box.s, cut = 16 * s, pad = 28 * s;
    /* The page: its field, a faint dot in every 6 px square, the lime shards fading out downwards over 900 px. */
    for (int y = 0; y < box.h; y++) {
        for (int x = 0; x < box.w; x++) {
            box.bits[(size_t)y * (size_t)box.w + (size_t)x] = 0xff000000u | (FIELD.r << 16) | (FIELD.g << 8) | FIELD.b;
        }
    }
    const int step = (int)fmax(4, floor(6 * s + 0.5));
    for (int y = step / 2; y < box.h; y += step) {
        for (int x = step / 2; x < box.w; x += step) {
            blend(x, y, WHITE, 11 / 255.0);
            blend(x - 1, y, WHITE, 11 / 255.0);
            blend(x, y - 1, WHITE, 11 / 255.0);
            blend(x - 1, y - 1, WHITE, 11 / 255.0);
        }
    }
    const double span = 900 * s;
    for (size_t f = 0; f < sizeof FACETS / sizeof FACETS[0]; f++) {
        double p[4][2];
        for (int i = 0; i < FACETS[f].n; i++) {
            p[i][0] = FACETS[f].p[i][0] / 1440.0 * box.w;
            p[i][1] = FACETS[f].p[i][1] / 900.0 * span;
        }
        for (int y = 0; y < box.h && y < span; y++) {
            const double down = y / span;
            /* The lime a little whiter at the top, a little darker at the bottom. */
            const Rgb top = {(BYTE)(0x8c + (255 - 0x8c) * 0.12), (BYTE)(0xf2 + (255 - 0xf2) * 0.12),
                             (BYTE)(0x3d + (255 - 0x3d) * 0.12)};
            const Rgb shard = {(BYTE)(top.r * (1 - down) + 0x8c * 0.70 * down),
                               (BYTE)(top.g * (1 - down) + 0xf2 * 0.70 * down),
                               (BYTE)(top.b * (1 - down) + 0x3d * 0.70 * down)};
            for (int x = 0; x < box.w; x++) {
                int n = 0;
                for (int i = 0; i < 2; i++) {
                    for (int j = 0; j < 2; j++) {
                        n += in_polygon(x + (i + 0.5) / 2, y + (j + 0.5) / 2, (const double (*)[2])p, FACETS[f].n);
                    }
                }
                if (n) {
                    blend(x, y, shard, FACETS[f].opacity * (1 - down) * n / 4.0);
                }
            }
        }
    }
    /* The shadow: black under the card, a little lower, fading out over 26 px around it. */
    const double sx = box.cx, sy = box.cy + 12 * s, reach = 26 * s;
    for (int y = (int)(sy - reach); y < (int)(sy + box.ch + reach); y++) {
        for (int x = (int)(sx - reach); x < (int)(sx + box.cw + reach); x++) {
            const double dx = fmax(fmax(sx - x, x - (sx + box.cw)), 0), dy = fmax(fmax(sy - y, y - (sy + box.ch)), 0);
            const double d = sqrt(dx * dx + dy * dy);
            if (d < reach) {
                blend(x, y, BLACK, 0.55 * (1 - d / reach) * (1 - d / reach));
            }
        }
    }
    /* The card, its sheen at the head fading out over 240 px, and a faint light along its top edge. */
    const double sheen = fmin(240 * s, box.ch);
    for (int y = (int)box.cy; y < (int)(box.cy + box.ch + 1); y++) {
        for (int x = (int)box.cx; x < (int)(box.cx + box.cw + 1); x++) {
            const double a = card_cover(x, y, box.cx, box.cy, box.cw, box.ch, cut);
            if (a > 0) {
                blend(x, y, PANEL, a);
                if (y - box.cy < sheen) {
                    blend(x, y, WHITE, a * 14 / 255.0 * pow(1 - (y - box.cy) / sheen, 1.6));
                }
            }
        }
    }
    for (int x = (int)box.cx; x < (int)(box.cx + box.cw - cut); x++) {
        blend(x, (int)box.cy, WHITE, 26 / 255.0);
    }
    /* The words: the question, what it means under it. */
    const double text_x = box.cx + pad + 18 * s, text_w = box.cw - pad * 2 - 18 * s;
    RECT q = {(LONG)text_x, (LONG)(box.cy + pad), (LONG)(text_x + text_w), (LONG)(box.cy + box.ch)};
    const int qh = text(box.message, box.title, CHALK, q, DT_WORDBREAK, 1);
    text(box.message, box.title, CHALK, q, DT_WORDBREAK, 0);
    RECT d = {(LONG)text_x, (LONG)(box.cy + pad + qh + 8 * s), (LONG)(text_x + text_w), (LONG)(box.cy + box.ch)};
    text(box.detail, box.body, ASH, d, DT_WORDBREAK, 0);
    /* The lamp: a 7 px dot of the error's red with its soft glow, beside the question's first line. */
    TEXTMETRICW tm;
    HGDIOBJ before = SelectObject(box.dc, box.title);
    GetTextMetricsW(box.dc, &tm);
    SelectObject(box.dc, before);
    const double lx = box.cx + pad + 7.5 * s, ly = box.cy + pad + tm.tmHeight / 2.0, r = 3.5 * s, glow = 10.5 * s;
    for (int y = (int)(ly - glow); y <= (int)(ly + glow); y++) {
        for (int x = (int)(lx - glow); x <= (int)(lx + glow); x++) {
            const double dist = sqrt((x + 0.5 - lx) * (x + 0.5 - lx) + (y + 0.5 - ly) * (y + 0.5 - ly));
            if (dist < glow) {
                blend(x, y, BAD, 110 / 255.0 * (1 - dist / glow));
            }
            int n = 0;
            for (int i = 0; i < 4; i++) {
                for (int j = 0; j < 4; j++) {
                    const double ex = x + (i + 0.5) / 4 - lx, ey = y + (j + 0.5) / 4 - ly;
                    n += ex * ex + ey * ey <= r * r;
                }
            }
            blend(x, y, BAD, n / 16.0);
        }
    }
    /* The button, lit down its height, and the keyboard's ring 3 px outside it. */
    const double bcut = 8 * s, gap = 3 * s, ring = fmax(2, 2 * s);
    for (int y = (int)(box.by - gap - ring); y <= (int)(box.by + box.bh + gap + ring); y++) {
        const double t = (y + 0.5 - box.by) / box.bh;
        const Rgb *c = LIT[box.state];
        const double k = t < 0.5 ? fmax(t, 0) / 0.5 : (fmin(t, 1) - 0.5) / 0.5;
        const Rgb a = t < 0.5 ? c[0] : c[1], b = t < 0.5 ? c[1] : c[2];
        const Rgb fill = {(BYTE)(a.r + (b.r - a.r) * k), (BYTE)(a.g + (b.g - a.g) * k), (BYTE)(a.b + (b.b - a.b) * k)};
        for (int x = (int)(box.bx - gap - ring); x <= (int)(box.bx + box.bw + gap + ring); x++) {
            blend(x, y, fill, button_cover(x, y, box.bx, box.by, box.bw, box.bh, bcut));
            const double outer = button_cover(x, y, box.bx - gap - ring, box.by - gap - ring, box.bw + 2 * (gap + ring),
                                              box.bh + 2 * (gap + ring), bcut + gap + ring);
            const double inner = button_cover(x, y, box.bx - gap, box.by - gap, box.bw + 2 * gap, box.bh + 2 * gap,
                                              bcut + gap);
            blend(x, y, CYAN, outer - inner);
        }
    }
    RECT bt = {(LONG)box.bx, (LONG)box.by, (LONG)(box.bx + box.bw), (LONG)(box.by + box.bh)};
    text(box.ok, box.bold, INK, bt, DT_CENTER | DT_VCENTER | DT_SINGLELINE, 0);
}

static int on_button(LPARAM l)
{
    const double x = (short)LOWORD(l), y = (short)HIWORD(l);
    return x >= box.bx && x < box.bx + box.bw && y >= box.by && y < box.by + box.bh;
}

static void restate(int state)
{
    if (state != box.state) {
        box.state = state;
        draw();
        InvalidateRect(box.window, NULL, FALSE);
    }
}

static LRESULT CALLBACK box_proc(HWND h, UINT msg, WPARAM w, LPARAM l)
{
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        BitBlt(dc, 0, 0, box.w, box.h, box.dc, 0, 0, SRCCOPY);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        /* The picture covers all of it. */
        return 1;
    case WM_MOUSEMOVE: {
        if (box.state != 2) {
            restate(on_button(l) ? 1 : 0);
        }
        TRACKMOUSEEVENT track = {sizeof track, TME_LEAVE, h, 0};
        TrackMouseEvent(&track);
        return 0;
    }
    case WM_MOUSELEAVE:
        if (box.state == 1) {
            restate(0);
        }
        return 0;
    case WM_LBUTTONDOWN:
        if (on_button(l)) {
            SetCapture(h);
            restate(2);
        }
        return 0;
    case WM_LBUTTONUP:
        if (box.state == 2) {
            ReleaseCapture();
            /* Let go on the button: answered; elsewhere: nothing. */
            if (on_button(l)) {
                box.done = 1;
            } else {
                restate(0);
            }
        }
        return 0;
    case WM_KEYDOWN:
        if (w == VK_RETURN || w == VK_SPACE || w == VK_ESCAPE) {
            box.done = 1;
        }
        return 0;
    case WM_CLOSE:
        box.done = 1;
        return 0;
    default:
        return DefWindowProcW(h, msg, w, l);
    }
}

#ifdef BOX_TEST
/* For a look at the box with no window (a build of its own with -DBOX_TEST): its picture in each state as BMPs in the
   current folder, box-0.bmp as it is, box-1.bmp under the pointer, box-2.bmp pressed. */
static void save_pictures(void)
{
    for (int state = 0; state < 3; state++) {
        box.state = state;
        draw();
        wchar_t name[32];
        swprintf(name, 32, L"box-%d.bmp", state);
        FILE *f = _wfopen(name, L"wb");
        if (!f) {
            continue;
        }
        BITMAPFILEHEADER file;
        BITMAPINFOHEADER head;
        ZeroMemory(&file, sizeof file);
        ZeroMemory(&head, sizeof head);
        const DWORD size = (DWORD)box.w * (DWORD)box.h * 4;
        file.bfType = 0x4d42;
        file.bfOffBits = sizeof file + sizeof head;
        file.bfSize = file.bfOffBits + size;
        head.biSize = sizeof head;
        head.biWidth = box.w;
        head.biHeight = -box.h;
        head.biPlanes = 1;
        head.biBitCount = 32;
        fwrite(&file, sizeof file, 1, f);
        fwrite(&head, sizeof head, 1, f);
        fwrite(box.bits, size, 1, f);
        fclose(f);
    }
}
#endif

/* Say what went wrong, in Windows' language (Korean or English), and wait for the answer; returns 1, the exit code. */
static int fail(const wchar_t *message_en, const wchar_t *detail_en, const wchar_t *message_ko, const wchar_t *detail_ko)
{
    int korean = PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_KOREAN;
#ifdef BOX_TEST
    /* The test build's language is the one asked for. */
    korean = _wgetenv(L"BOX_LANG") && wcscmp(_wgetenv(L"BOX_LANG"), L"ko") == 0;
#endif
    /* Sharp at Windows' scale: drawn at it, never stretched. */
    SetProcessDPIAware();
    HDC screen = GetDC(NULL);
    box.s = GetDeviceCaps(screen, LOGPIXELSY) / 96.0;
    ReleaseDC(NULL, screen);
    const double s = box.s;
    box.message = korean ? message_ko : message_en;
    box.detail = korean ? detail_ko : detail_en;
    box.ok = korean ? L"확인" : L"OK";
    /* The PC client's sizes: the question at 13 pt bold, the rest at 10 pt, the button's words bold (theme.Fonts). */
    const wchar_t *face = korean ? L"Malgun Gothic" : L"Segoe UI";
    box.title = CreateFontW(-(int)(13 * 96 / 72.0 * s + 0.5), 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                            CLEARTYPE_QUALITY, 0, face);
    box.body = CreateFontW(-(int)(10 * 96 / 72.0 * s + 0.5), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                           CLEARTYPE_QUALITY, 0, face);
    box.bold = CreateFontW(-(int)(10 * 96 / 72.0 * s + 0.5), 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                           CLEARTYPE_QUALITY, 0, face);
    /* Measured on a screen-like picture first: the card is as tall as what it says. */
    box.dc = CreateCompatibleDC(NULL);
    const double margin = 44 * s, pad = 28 * s;
    box.cw = 480 * s;
    const double text_w = box.cw - pad * 2 - 18 * s;
    RECT m = {0, 0, (LONG)text_w, 10000};
    const int qh = text(box.message, box.title, CHALK, m, DT_WORDBREAK, 1);
    RECT n = {0, 0, (LONG)text_w, 10000};
    const int dh = text(box.detail, box.body, ASH, n, DT_WORDBREAK, 1);
    SIZE ok_size;
    HGDIOBJ before = SelectObject(box.dc, box.bold);
    GetTextExtentPoint32W(box.dc, box.ok, (int)wcslen(box.ok), &ok_size);
    SelectObject(box.dc, before);
    box.bw = fmax(110 * s, ok_size.cx + 40 * s);
    box.bh = 40 * s;
    box.ch = pad + qh + 8 * s + dh + 24 * s + box.bh + pad - 4 * s;
    box.cx = margin;
    box.cy = margin;
    box.bx = box.cx + box.cw - pad - box.bw;
    box.by = box.cy + box.ch - (pad - 4 * s) - box.bh;
    box.w = (int)ceil(box.cw + margin * 2);
    box.h = (int)ceil(box.ch + margin * 2);
    BITMAPINFO info;
    ZeroMemory(&info, sizeof info);
    info.bmiHeader.biSize = sizeof info.bmiHeader;
    info.bmiHeader.biWidth = box.w;
    info.bmiHeader.biHeight = -box.h;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    void *bits = NULL;
    box.bitmap = CreateDIBSection(box.dc, &info, DIB_RGB_COLORS, &bits, NULL, 0);
    if (!box.bitmap || !bits) {
        /* No picture to draw on: Windows' own box, so that it is still said. */
        MessageBoxW(NULL, box.message, L"OpenDMTQ", MB_OK | MB_ICONERROR);
        return 1;
    }
    box.bits = (DWORD *)bits;
    box.old = SelectObject(box.dc, box.bitmap);
    draw();
#ifdef BOX_TEST
    save_pictures();
    return 1;
#endif
    /* A window of Windows' own frame around the picture, with the bundle's icon, in the middle of the work area. */
    WNDCLASSEXW c;
    ZeroMemory(&c, sizeof c);
    c.cbSize = sizeof c;
    c.lpfnWndProc = box_proc;
    c.hInstance = GetModuleHandleW(NULL);
    c.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_ARROW);
    c.hIcon = LoadIconW(c.hInstance, MAKEINTRESOURCEW(1));
    c.lpszClassName = L"OpenDMTQErrorBox";
    RegisterClassExW(&c);
    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    RECT frame = {0, 0, box.w, box.h};
    AdjustWindowRectEx(&frame, style, FALSE, 0);
    const int fw = frame.right - frame.left, fh = frame.bottom - frame.top;
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    box.window = CreateWindowExW(0, c.lpszClassName, L"OpenDMTQ", style, work.left + (work.right - work.left - fw) / 2,
                                 work.top + (work.bottom - work.top - fh) / 2, fw, fh, NULL, NULL, c.hInstance, NULL);
    if (box.window) {
        ShowWindow(box.window, SW_SHOW);
        SetForegroundWindow(box.window);
        SetFocus(box.window);
        MSG msg;
        while (!box.done && GetMessageW(&msg, NULL, 0, 0) > 0) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        DestroyWindow(box.window);
    } else {
        MessageBoxW(NULL, box.message, L"OpenDMTQ", MB_OK | MB_ICONERROR);
    }
    return 1;
}

int wmain(void)
{
    static wchar_t dir[PATH_ROOM], python[PATH_ROOM], script[PATH_ROOM], line[PATH_ROOM * 3];
    /* This program's own path; the bundle is the folder it is in. */
    DWORD n = GetModuleFileNameW(NULL, dir, PATH_ROOM);
    if (n == 0 || n >= PATH_ROOM) {
        return fail(L"OpenDMTQ could not find its own folder.", UNPACK_EN, L"OpenDMTQ가 자기 폴더를 찾지 못했습니다.", UNPACK_KO);
    }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) {
        return fail(L"OpenDMTQ could not find its own folder.", UNPACK_EN, L"OpenDMTQ가 자기 폴더를 찾지 못했습니다.", UNPACK_KO);
    }
    *slash = 0;
    /* The bundle's Python and the host program, by full path. */
    swprintf(python, PATH_ROOM, L"%ls\\runtime\\python\\python.exe", dir);
    swprintf(script, PATH_ROOM, L"%ls\\app\\host\\opendmtq_host", dir);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        return fail(L"Parts of OpenDMTQ are missing.", UNPACK_EN, L"OpenDMTQ의 파일 일부가 없습니다.", UNPACK_KO);
    }
    /* Isolated (-I: no Python settings of this PC change it) and in UTF-8 (-X utf8: Korean file names read right),
       then the host program and what this program was given. */
    swprintf(line, PATH_ROOM * 3, L"\"%ls\" -I -X utf8 \"%ls\" %ls", python, script, arguments());
    /* The window's title, and UTF-8 for what is printed in it. */
    SetConsoleTitleW(L"OpenDMTQ");
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    /* Ctrl+C and closing the window reach the host program through the window it shares; this one only waits. */
    SetConsoleCtrlHandler(NULL, TRUE);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    /* This program's own input and output, whatever they are: the window, or files and pipes when a script started it
       with its output sent elsewhere (handed on explicitly: Python stops at once without them). */
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof pi);
    /* In the bundle's folder, so that a relative path given to a command means the same as in a terminal there. The
       handles above are inherited, nothing else of this program is open. */
    if (!CreateProcessW(python, line, NULL, NULL, TRUE, 0, NULL, dir, &si, &pi)) {
        return fail(L"OpenDMTQ could not start its Python.", L"runtime\\python did not start. " UNPACK_EN,
                    L"OpenDMTQ가 Python을 시작하지 못했습니다.", L"runtime\\python이 시작되지 않았습니다.\n" UNPACK_KO);
    }
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
