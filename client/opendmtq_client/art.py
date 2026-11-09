"""Pictures the launcher draws for itself, in the OpenDMTQ site's look.

Everything here is drawn in code: no game art ships with the client. Shapes are drawn three times larger and scaled
down, because Tk's own canvas does not smooth diagonal edges.
"""

import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from opendmtq_client import theme

# Draw at this many times the final size, then scale down: smooth edges without a drawing library.
SS = 3

# Chrome, top to bottom: bright, a dark band where the horizon reflects, bright again (the site's wordmark).
CHROME = ((0.0, "#ffffff"), (0.46, "#e4e9ee"), (0.54, "#76808b"), (0.72, "#b3bbc4"), (1.0, "#f4f6f8"))
# How far titles lean, as the site's wordmark and the TECHNIKA Q logo do: 12 degrees.
LEAN = math.tan(math.radians(12))


def _rgb(hex_colour):
    """'#1f5bff' -> (31, 91, 255)."""
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lit_chrome(colour):
    """Chrome that turns into a colour towards its foot, for the last letter of a mark (the wordmark's lime Q)."""
    return ((0.0, "#ffffff"), (0.6, colour), (1.0, colour))


def _ramp(size, stops):
    """A vertical gradient through several colours: stops are (place 0..1, colour)."""
    w, h = size
    column = Image.new("RGB", (1, max(2, h)))
    for y in range(column.height):
        t = y / float(column.height - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                a, b = _rgb(c0), _rgb(c1)
                column.putpixel((0, y), tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3)))
                break
    return column.resize((max(1, w), max(1, h)), Image.BILINEAR)


def _dots(img, step, alpha):
    """The site's perforated metal: a faint grid of points over a surface."""
    layer = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(layer)
    for y in range(step // 2, img.height, step):
        for x in range(step // 2, img.width, step):
            draw.point((x, y), fill=alpha)
    img.paste(Image.new("RGB", img.size, (255, 255, 255)), (0, 0), layer)


def shards(width, height, seed=7, density=1.0, colours=None):
    """The page behind its title: gunmetal with shards cutting in from the right, the Technika shards at the site's
    edges. The shards take the section's colour (PLAY's lime unless told otherwise)."""
    colours = colours or theme.SECTION_COLOURS["home"]
    w, h = width * SS, height * SS
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), _rgb(theme.BG))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bright, deep = _rgb(colours["light"]), _rgb(colours["deep"])
    # Large dark planes first, then bright splinters over them, all leaning the same way.
    for i in range(int(16 * density)):
        splinter = i >= 6
        # Shards start on the right two thirds so the title on the left stays on dark metal.
        x = rng.uniform(0.38, 1.08) * w
        y = rng.uniform(-0.3, 1.1) * h
        length = rng.uniform(0.45, 1.3) * h * (1.3 if not splinter else 1.0)
        spread = rng.uniform(0.05, 0.20) * w
        # A long thin triangle: one sharp tip, one short base edge, like broken glass.
        points = [(x, y), (x + spread, y - length * 0.30), (x - spread * rng.uniform(0.3, 1.0), y + length)]
        # Splinters half seen through, so the section's colour lights the page without shouting over the title.
        alpha = rng.randint(100, 150) if splinter else rng.randint(120, 190)
        draw.polygon(points, fill=(bright if splinter else deep) + (alpha,))
    img.paste(layer, (0, 0), layer)
    img = img.resize((width, height), Image.LANCZOS)
    # A soft fade from the left, so the title reads on plain metal.
    fade = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
    plain = Image.new("RGB", (width, height), _rgb(theme.BG))
    _dots(plain, 6, 12)
    return Image.composite(img, plain, fade.point(lambda v: min(255, int(v * 1.6))))


def _hangul(text):
    """True when the text has Hangul, which the wide face lacks."""
    return any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in text)


def _lean(img, slope):
    """The picture sheared to lean right by `slope` (x moves right as y goes up), wider by what the lean takes."""
    extra = int(math.ceil(img.height * slope))
    wide = Image.new(img.mode, (img.width + extra, img.height), (0, 0, 0, 0))
    wide.paste(img, (0, 0))
    # Image.transform maps each output pixel back to the input: x_in = x_out + slope * y_out - extra.
    return wide.transform(wide.size, Image.AFFINE, (1, slope, -extra, 0, 1, 0), resample=Image.BICUBIC)


def chrome_text(parts, size, scale=1.0):
    """Words with a chrome face, a dark rim and a soft shadow, leaning like the site's wordmark.

    parts: [(text, stops)] drawn one after another, so a mark can end in another colour (the wordmark's lime Q). Latin
    is set in the leaning wide face; Korean, which it lacks, in Pretendard Bold, leant by shearing the picture. Returns
    an RGBA picture just big enough, and the baseline's height in it.
    """
    whole = "".join(t for t, _ in parts)
    korean = _hangul(whole)
    # Pretendard's letters sit smaller in their size than the wide face's capitals: a little larger, the same height.
    font = ImageFont.truetype(theme.HANGUL_TITLE_FILE, int(round(size * 1.15))) if korean else \
        ImageFont.truetype(theme.WIDE_ITALIC_FILE, size)
    rim = max(1, int(round(1.4 * scale)))
    pad = rim + int(6 * scale)
    ascent, descent = font.getmetrics()
    # Room for the italic's last letter, which leans past its advance.
    width = int(sum(font.getlength(t) for t, _ in parts)) + 2 * pad + int(size * 0.18)
    height = ascent + descent + 2 * pad
    baseline = pad + ascent
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fill_mask = Image.new("L", img.size, 0)
    rim_mask = Image.new("L", img.size, 0)
    colour = Image.new("RGB", img.size, (0, 0, 0))
    x = pad
    # The gradient spans the capitals, so the dark band sits across every letter at the same height.
    top = baseline - int(font.getbbox("H")[3] - font.getbbox("H")[1])
    for text, stops in parts:
        piece = Image.new("L", img.size, 0)
        ImageDraw.Draw(piece).text((x, baseline), text, font=font, fill=255, anchor="ls")
        ImageDraw.Draw(rim_mask).text((x, baseline), text, font=font, fill=255, anchor="ls", stroke_width=rim,
                                      stroke_fill=255)
        ramp = _ramp((width, baseline - top + 2), stops)
        layer = Image.new("RGB", img.size, _rgb(stops[-1][1]))
        layer.paste(_rgb(stops[0][1]), (0, 0, width, top))
        layer.paste(ramp, (0, top))
        colour.paste(layer, (0, 0), piece)
        fill_mask.paste(255, (0, 0), piece)
        x += font.getlength(text)
    shadow = rim_mask.filter(ImageFilter.GaussianBlur(3 * scale)).point(lambda v: int(v * 0.7))
    img.paste((0, 0, 0, 255), (0, int(2 * scale)), shadow)
    img.paste(_rgb(theme.INK) + (255,), (0, 0), rim_mask)
    rgba = colour.convert("RGBA")
    img.paste(rgba, (0, 0), fill_mask)
    if korean:
        # Pretendard stands upright: the picture leans instead, as the Latin face does by itself.
        img = _lean(img, LEAN)
    return img, baseline


def header(width, height, seed=7, colours=None, title=None, title_tail=None, scale=1.0, title_at=(32, 98)):
    """The page header: shards in the section's colour and the page's title in leaning chrome (its tail, such as the
    Q of OpenDMTQ, in the section's colour).

    title_at is the title's left edge and baseline in logical pixels.
    """
    colours = colours or theme.SECTION_COLOURS["home"]
    img = shards(width, height, seed=seed, colours=colours).convert("RGBA")
    if title:
        parts = [(title, CHROME)]
        if title_tail and title.endswith(title_tail):
            parts = [(title[:-len(title_tail)], CHROME), (title_tail, lit_chrome(colours["accent"]))]
        words, baseline = chrome_text(parts, int(round(34 * scale)), scale)
        pad = int(6 * scale) + max(1, int(round(1.4 * scale)))
        img.alpha_composite(words, (int(title_at[0] * scale) - pad, int(title_at[1] * scale) - baseline))
    return img.convert("RGB")


def logo(width, scale=1.0, label="PC", accent=theme.OK, version=None):
    """OpenDMTQ's wordmark as the site draws it, `width` pixels wide: OPEN spaced out in small leaning letters beside a
    splinter that runs from grey into the accent, then DMTQ in leaning chrome with a lime Q, and a small label after it.
    With `version`, a small plate with it at the end of the OPEN line, where the splinter stops short of it."""
    small = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(8, int(round(10 * scale))))
    tiny = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(8, int(round(11 * scale))))
    label_w = int(tiny.getlength(label)) + int(8 * scale)
    # DMTQ as large as the width allows beside its label.
    size = int(round(42 * scale))
    while size > 12:
        big, baseline = chrome_text([("DMT", CHROME), ("Q", lit_chrome(accent))], size, scale)
        if big.width + label_w <= width:
            break
        size -= 1
    pad = int(6 * scale) + max(1, int(round(1.4 * scale)))
    top = int(round(15 * scale))
    img = Image.new("RGBA", (width, top + big.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # OPEN, letter by letter with air between them (the site's 0.2 em), starting a little in: its lean starts further right.
    x = pad + int(4 * scale)
    for ch in "OPEN":
        draw.text((x, top), ch, font=small, fill=(0xf4, 0xf6, 0xf8, 255), anchor="ls")
        x += small.getlength(ch) + 2.6 * scale
    # The splinter: a leaning bar after OPEN up to DMTQ's right end, grey turning into the accent (the site's ::after,
    # which stops half its letters' height short of the big word's end).
    left, right = x + 5 * scale, max(x + 12 * scale, big.width - pad - int(size * 0.17))
    plate = None
    if version:
        # The version's plate: its words in the text face, measured first so the splinter can stop before it.
        face = ImageFont.truetype(theme.TEXT_BOLD_FILE, max(9, int(round(11 * scale))))
        text_w = face.getlength(version)
        plate_w, plate_h = int(text_w + 12 * scale), int(round(17 * scale))
        # Right-aligned to the picture, its middle on the OPEN line's middle (OPEN's letters stand about 7 px tall).
        plate = (width - plate_w, int(top - 3.5 * scale - plate_h / 2.0), plate_w, plate_h, face)
        right = min(right, width - plate_w - 7 * scale)
    foot, head = top - 1.5 * scale, top - 5.5 * scale
    slant = (foot - head) * LEAN
    mask = _mask(img.size, lambda d, s: d.polygon([((left + slant) * s, head * s), (right * s, head * s),
                                                   ((right - slant) * s, foot * s), (left * s, foot * s)], fill=255))
    ramp = Image.linear_gradient("L").rotate(90, expand=True).resize(img.size)
    tint = Image.composite(Image.new("RGBA", img.size, _rgb(accent) + (255,)),
                           Image.new("RGBA", img.size, (0x8f, 0x99, 0xa4, 255)), ramp)
    img.paste(tint, (0, 0), mask)
    img.alpha_composite(big, (0, top))
    # The label sits on the big letters' baseline, after them, in the accent (the site's .s).
    draw.text((big.width + int(2 * scale), top + baseline), label, font=tiny, fill=_rgb(accent) + (255,), anchor="ls")
    if plate is not None:
        px_, py_, pw, ph, face = plate
        # Quiet metal with the version in light grey: read at a glance, never louder than the name (7:1 contrast).
        draw.rounded_rectangle((px_, max(0, py_), px_ + pw - 1, max(0, py_) + ph - 1), radius=int(round(4 * scale)),
                               fill=_rgb(theme.RAIL) + (255,), outline=_rgb(theme.LINE) + (255,))
        draw.text((px_ + pw / 2.0, max(0, py_) + ph / 2.0), version, font=face, fill=_rgb(theme.MUTED) + (255,),
                  anchor="mm")
    return img


def play_button(width, height, state="normal"):
    """The PLAY button: a lime slab with its corners cut at 45 degrees, the site's main button in the game's shape."""
    w, h = width * SS, height * SS
    cut = int(h * 0.28)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    top, bottom = {
        "normal": ("#b2f777", theme.OK),
        "hover": ("#c6fa98", "#9df55a"),
        "pressed": (theme.OK, "#6fcf22"),
        "disabled": ("#262d37", "#1d232b"),
        "playing": ("#2c3646", "#222a36"),
    }[state]
    # A vertical gradient, then the cut-corner outline as its mask.
    grad = Image.linear_gradient("L").resize((w, h))
    body = Image.composite(Image.new("RGBA", (w, h), _rgb(bottom) + (255,)),
                           Image.new("RGBA", (w, h), _rgb(top) + (255,)), grad)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(cut_outline(0, 0, w, h, cut), fill=255)
    img.paste(body, (0, 0), mask)
    if state in ("normal", "hover"):
        # A thin bright edge along the top, the chrome highlight.
        edge = Image.new("L", (w, h), 0)
        ImageDraw.Draw(edge).line([(cut, SS), (w - SS, SS)], fill=150, width=SS)
        img.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), edge)
    return img.resize((width, height), Image.LANCZOS)


def toggle(on, width, height, enabled=True, colour=None, knob=None):
    """An on/off switch: a pill with a round knob, in the section's colour when on (the knob in its dark ink)."""
    w, h = width * SS, height * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    track = (colour or theme.OK) if on else theme.RAIL
    if not enabled:
        track = "#20262e"
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=_rgb(track) + (255,))
    pad = int(h * 0.16)
    d = h - 2 * pad
    x = w - pad - d if on else pad
    face = (knob if on and knob else theme.TEXT) if enabled else theme.FAINT
    draw.ellipse([x, pad, x + d, pad + d], fill=_rgb(face) + (255,))
    return img.resize((width, height), Image.LANCZOS)


def knob(size, colour=theme.TEXT, ring=theme.OK):
    """A slider knob: a light disc with a ring in the section's colour."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, s - 1, s - 1], fill=_rgb(ring) + (255,))
    inset = int(s * 0.22)
    draw.ellipse([inset, inset, s - 1 - inset, s - 1 - inset], fill=_rgb(colour) + (255,))
    return img.resize((size, size), Image.LANCZOS)


def bar(width, height, fraction, colour, track=theme.RAIL):
    """A progress bar: the track with its done part in a colour, rounded at both ends (downloads)."""
    w, h = width * SS, height * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=_rgb(track) + (255,))
    done = int(round(max(0.0, min(1.0, fraction)) * (w - 1)))
    # Nothing done yet shows the track alone; a sliver narrower than the round ends would draw a dot.
    if done >= h:
        draw.rounded_rectangle([0, 0, done, h - 1], radius=h // 2, fill=_rgb(colour) + (255,))
    return img.resize((width, height), Image.LANCZOS)


# ------------------------------------------------------------------------------------------------ dialogs
#
# A dialog is drawn as opaque pictures only: the dimmed window behind it, the panel over that window's own pixels,
# and each button over the panel's own pixels. Tk then never has to blend a half-transparent picture, which it
# does differently on each platform.


def cut_outline(x, y, width, height, cut):
    """A pressable's outline (buttons, PLAY): a box with its top-left and bottom-right corners cut at 45 degrees."""
    return [(x + cut, y), (x + width, y), (x + width, y + height - cut), (x + width - cut, y + height),
            (x, y + height), (x, y + cut)]


def card_outline(x, y, width, height, cut):
    """A panel's outline (cards, dialogs): one corner cut, the top right, as the site's panels have it."""
    return [(x, y), (x + width - cut, y), (x + width, y + cut), (x + width, y + height), (x, y + height)]


def _gradient(size, top, bottom):
    """An opaque picture fading from one colour at the top to another at the bottom."""
    grad = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, _rgb(bottom)), Image.new("RGB", size, _rgb(top)), grad)


def _mask(size, draw_shape):
    """A smooth-edged mask: the shape drawn SS times larger, then scaled down to `size`."""
    big = Image.new("L", (size[0] * SS, size[1] * SS), 0)
    draw_shape(ImageDraw.Draw(big), SS)
    return big.resize(size, Image.LANCZOS)


def _soft(window, radius):
    """The window out of focus. Blurred at half size, then scaled back: the same look for a quarter of the work."""
    w, h = window.size
    small = window.resize((max(1, w // 2), max(1, h // 2)), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(max(1, radius / 2))).resize((w, h), Image.BILINEAR)


def dialog_scene(window, box, cut, accent, scale):
    """What shows behind a dialog: the window blurred and dimmed, with the panel's shadow under it and a faint glow of
    its colour around it.

    `window` is the window as a picture (snapshot.py) and `box` the panel's (x, y, width, height) in it. Returns the
    scene and the blurred window before dimming, which the panel's glass is made from.
    """
    w, h = window.size
    soft = _soft(window, 9 * scale)
    scene = Image.blend(soft, Image.new("RGB", (w, h), _rgb(theme.BG)), 0.58)
    x, y, bw, bh = box
    # The shadow and the glow are only blurred near the panel: a blur over the whole window would cost much more.
    reach = int(40 * scale)
    area = (max(0, x - reach), max(0, y - reach), min(w, x + bw + reach), min(h, y + bh + reach + int(12 * scale)))
    size = (area[2] - area[0], area[3] - area[1])
    for colour, strength, drop, blur in (("#000000", 0.72, 12, 20), (accent, 0.16, 0, 28)):
        mask = Image.new("L", size, 0)
        outline = card_outline(x - area[0], y - area[1] + int(drop * scale), bw, bh, cut)
        ImageDraw.Draw(mask).polygon(outline, fill=int(255 * strength))
        mask = mask.filter(ImageFilter.GaussianBlur(blur * scale))
        region = scene.crop(area)
        region.paste(Image.new("RGB", size, _rgb(colour)), (0, 0), mask)
        scene.paste(region, area[:2])
    return scene, soft


def dialog_panel(scene, soft, box, cut, tab, ring, accent, scale):
    """The panel: gunmetal glass over the blurred window with a sheen at its head and a light rim along its top (the
    site's frosted panels), the title tab hanging from the top edge, and the ring the glyph sits in.

    tab: (width, height, slant, top colour, bottom colour); ring: (centre x, centre y, diameter), both in the panel's own
    pixels. Returns an opaque picture of the box.
    """
    x, y, bw, bh = box
    panel = scene.crop((x, y, x + bw, y + bh))
    # Glass: the blurred window through gunmetal, as the site's panels (86 %), brighter at its head.
    glass = Image.blend(soft.crop((x, y, x + bw, y + bh)), Image.new("RGB", (bw, bh), _rgb(theme.PANEL)), 0.86)
    reach = max(1, int(240 * scale))
    sheen = Image.linear_gradient("L").resize((1, reach)).point(lambda v: int(14 * (1 - v / 255.0) ** 1.6))
    glass.paste(Image.new("RGB", (bw, min(reach, bh)), (255, 255, 255)), (0, 0), sheen.resize((bw, reach)).crop(
        (0, 0, bw, min(reach, bh))))
    shape = _mask((bw, bh), lambda d, s: d.polygon(card_outline(0, 0, bw * s, bh * s, cut * s), fill=255))
    panel.paste(glass, (0, 0), shape)
    # The edge: one pixel of seam, lit along the top and the cut like polished metal.
    edge = _mask((bw, bh), lambda d, s: d.line(card_outline(0, 0, bw * s - s, bh * s - s, cut * s) + [(0, 0)],
                                                fill=255, width=s))
    panel.paste(_gradient((bw, bh), "#626d7c", theme.LINE), (0, 0), edge)
    # The tab: wider at the panel's edge, narrowing downwards, in the dialog's colour.
    tw, th, slant, top, bottom = tab
    tx = (bw - tw) // 2
    tab_shape = _mask((bw, bh), lambda d, s: d.polygon(
        [(tx * s, 0), ((tx + tw) * s, 0), ((tx + tw - slant) * s, th * s), ((tx + slant) * s, th * s)], fill=255))
    filled = Image.new("RGB", (bw, bh))
    filled.paste(_gradient((tw, th), top, bottom), (tx, 0))
    panel.paste(filled, (0, 0), tab_shape)
    shine = _mask((bw, bh), lambda d, s: d.line([((tx + 2) * s, s), ((tx + tw - 2) * s, s)], fill=130, width=s))
    panel.paste(Image.new("RGB", (bw, bh), (255, 255, 255)), (0, 0), shine)
    # The ring: a faint disc of the colour, a bright line around it and a soft glow outside.
    cx, cy, d = ring
    r = d / 2.0
    glow = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(glow).ellipse([cx - r, cy - r, cx + r, cy + r], outline=150, width=max(2, int(3 * scale)))
    glow = glow.filter(ImageFilter.GaussianBlur(6 * scale))
    disc = _mask((bw, bh), lambda dr, s: dr.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
                                                    fill=30))
    line = _mask((bw, bh), lambda dr, s: dr.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
                                                    outline=245, width=max(2, int(round(2 * scale))) * s))
    colour = Image.new("RGB", (bw, bh), _rgb(accent))
    for layer in (glow, disc, line):
        panel.paste(colour, (0, 0), layer)
    return panel


# A button's colours for each look: (top, bottom) of its fill, its edge (None for none), and its words.
_OFF = ("#20262e", "#1c2128")
BUTTON_LOOKS = {
    "neutral": {"normal": (theme.RAIL_UP, theme.RAIL), "hover": ("#414b57", theme.RAIL_UP),
                "pressed": (theme.RAIL, "#20262e"), "disabled": _OFF,
                "edge": ("#5a6573", theme.LINE), "text": theme.TEXT},
    "danger": {"normal": ("#ff8592", theme.BAD), "hover": ("#ff9ba6", "#ff7484"), "pressed": (theme.BAD, "#e04558"),
               "disabled": _OFF, "edge": None, "text": "#2b0409"},
    "warn": {"normal": ("#ffdc6e", theme.WARN), "hover": ("#ffe48d", "#ffd556"), "pressed": (theme.WARN, "#e0b22a"),
             "disabled": _OFF, "edge": None, "text": theme.INK},
    "home": {"normal": ("#b2f777", theme.OK), "hover": ("#c6fa98", "#9df55a"), "pressed": (theme.OK, "#6fcf22"),
             "disabled": _OFF, "edge": None, "text": "#0d1c04"},
    "songs": {"normal": ("#9ae3ff", theme.CYAN), "hover": ("#b2eaff", "#84dcff"), "pressed": (theme.CYAN, "#45bfee"),
              "disabled": _OFF, "edge": None, "text": "#04202e"},
    "ranking": {"normal": ("#d6b2ff", theme.VIOLET), "hover": ("#e0c4ff", "#cfa3ff"),
                "pressed": (theme.VIOLET, "#a874ee"), "disabled": _OFF, "edge": None, "text": "#1b0a34"},
    "admin": {"normal": ("#ffc86e", theme.AMBER), "hover": ("#ffd38d", "#ffbf57"), "pressed": (theme.AMBER, "#e0952a"),
              "disabled": _OFF, "edge": None, "text": "#2a1700"},
    # Removing or starting over: metal with a red tint and red words, filled red under the pointer.
    "danger_quiet": {"normal": ("#5a333b", "#4a2a31"), "hover": ("#ff8592", theme.BAD),
                     "pressed": (theme.BAD, "#e04558"), "disabled": _OFF,
                     "edge": ("#7a4650", "#4a2a31"), "text": "#ffc0c7", "hover_text": "#2b0409"},
}
# The section a page belongs to gives its main buttons their look.
SECTION_LOOKS = {"home": "home", "songs": "songs", "ranking": "ranking", "admin": "admin"}


def button_face(size, margin, look, state, focused, scale, under=None, bg=None):
    """A button's picture, cut at two corners like PLAY: quiet metal, or a fill in a section's colour.

    `under` is what lies beneath (a dialog's panel pixels) or `bg` a plain colour; `margin` pixels on every side hold
    the focus ring when the button has the keyboard. With no margin (a page's button, which keeps its size) the ring
    runs just inside the outline instead: cyan on metal, the words' dark ink on a coloured fill, where cyan would not
    show.
    """
    colours = BUTTON_LOOKS[look]
    w, h = size
    img = under.copy() if under is not None else Image.new("RGB", size, _rgb(bg or theme.BG))
    bw, bh = w - 2 * margin, h - 2 * margin
    cut = max(4, int(round(8 * scale)))
    shape = _mask((w, h), lambda d, s: d.polygon(cut_outline(margin * s, margin * s, bw * s, bh * s, cut * s),
                                                 fill=255))
    filled = Image.new("RGB", (w, h))
    filled.paste(_gradient((bw, bh), *colours[state]), (margin, margin))
    img.paste(filled, (0, 0), shape)
    if colours["edge"] and state != "disabled":
        edge = _mask((w, h), lambda d, s: d.line(cut_outline(margin * s, margin * s, bw * s - s, bh * s - s, cut * s)
                                                  + [((margin + cut) * s, margin * s)], fill=200, width=s))
        edged = Image.new("RGB", (w, h))
        edged.paste(_gradient((bw, bh), *colours["edge"]), (margin, margin))
        img.paste(edged, (0, 0), edge)
    elif state != "disabled":
        # A bright line along the top, the chrome highlight (as on PLAY).
        shine = _mask((w, h), lambda d, s: d.line([((margin + cut) * s, (margin + 1) * s),
                                                   ((margin + bw - 2) * s, (margin + 1) * s)], fill=110, width=s))
        img.paste(Image.new("RGB", (w, h), (255, 255, 255)), (0, 0), shine)
    if focused and not margin:
        # Inside the outline, parallel to it: the cut corners move in by about 0.4 of the inset (45 degrees).
        inset = max(2, int(round(3 * scale)))
        inner_cut = max(1, cut - int(round(inset * 0.4)))
        ring = _mask((w, h), lambda d, s: d.line(
            cut_outline(inset * s, inset * s, (bw - 2 * inset) * s - s, (bh - 2 * inset) * s - s, inner_cut * s)
            + [((inset + inner_cut) * s, inset * s)], fill=255, width=max(2, int(round(2 * scale))) * s))
        if look == "neutral" or (colours["edge"] is not None and state not in ("hover", "pressed")):
            # On metal: the keyboard's own cyan.
            tint = theme.CYAN
        elif state in ("hover", "pressed"):
            # On the fill a pointer brings: the dark words' colour of that fill.
            tint = colours.get("hover_text", colours["text"])
        else:
            # On a coloured fill: its dark words' colour, where cyan would not show.
            tint = colours["text"]
        img.paste(Image.new("RGB", (w, h), _rgb(tint)), (0, 0), ring)
    elif focused:
        # The keyboard's ring follows the button's own outline, a little outside it, in the focus colour.
        gap = max(2, int(round(3 * scale)))
        ring = _mask((w, h), lambda d, s: d.line(
            cut_outline((margin - gap) * s, (margin - gap) * s, (bw + 2 * gap) * s - s, (bh + 2 * gap) * s - s,
                        (cut + gap) * s) + [((margin + cut) * s, (margin - gap) * s)],
            fill=255, width=max(2, int(round(2 * scale))) * s))
        img.paste(Image.new("RGB", (w, h), _rgb(theme.CYAN)), (0, 0), ring)
    return img


def corner(size, inside, outside, seam):
    """The top-right corner of a panel, cut: what a card's cut corner shows over its square frame."""
    s = size * SS
    img = Image.new("RGB", (s, s), _rgb(outside))
    draw = ImageDraw.Draw(img)
    draw.polygon([(0, 0), (s, s), (0, s)], fill=_rgb(inside))
    draw.line([(0, 0), (s, s)], fill=_rgb(seam), width=SS)
    return img.resize((size, size), Image.LANCZOS)


def mark(size):
    """The OpenDMTQ mark, as the site's icon draws it: the wordmark's green Q, leaning, on a dark rounded square."""
    s = size * SS
    # The site's icon is drawn on a 32-unit square: one unit here.
    u = s / 32.0
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, s - 1, s - 1], radius=4 * u, fill=_rgb("#15171b") + (255,))
    # The Q upright: a rounded box's outline and its tail, then leant as the site's icon (skewX(-12) and a nudge right).
    q = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(q)
    stroke = int(round(4.2 * u))
    half = stroke / 2.0
    draw.rounded_rectangle([(8.5 * u) - half, (5 * u) - half, (21.5 * u) + half, (26 * u) + half], radius=4.5 * u + half,
                           outline=255, width=stroke)
    draw.line([(17.5 * u, 21.5 * u), (23 * u, 29 * u)], fill=255, width=stroke)
    # Leant around the top: x moves left as y grows, as SVG's skewX(-12) does, then 3.5 units right.
    k = math.tan(math.radians(12))
    q = q.transform(q.size, Image.AFFINE, (1, k, -3.5 * u, 0, 1, 0), resample=Image.BICUBIC)
    img.paste(Image.new("RGBA", (s, s), _rgb("#7dff4f") + (255,)), (0, 0), q)
    return img.resize((size, size), Image.LANCZOS)
