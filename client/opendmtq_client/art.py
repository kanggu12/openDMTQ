"""Pictures the launcher draws for itself, in the OpenDMTQ site's look.

Everything here is drawn in code: no game art ships with the client. Shapes are drawn three times larger and scaled
down, because Tk's own canvas does not smooth diagonal edges.
"""

import collections
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from opendmtq_client import theme

# Draw at this many times the final size, then scale down: smooth edges without a drawing library.
SS = 3


def _rgb(hex_colour):
    """'#1f5bff' -> (31, 91, 255)."""
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------------------------------------ the site's wordmark

# The wordmark's metal (server/portal/style.css .logo .m): over the line box of DMTQ, top to bottom.
WORDMARK_CHROME = ((0.0, "#ffffff"), (0.46, "#e4e9ee"), (0.54, "#76808b"), (0.72, "#b3bbc4"), (1.0, "#f4f6f8"))


def _vertical(size, stops, top=0.0, span=None):
    """A vertical gradient picture of `size`, its stops placed over `span` pixels starting `top` pixels from the
    picture's top (as a CSS gradient over a box that is not the picture), the end colours held beyond them."""
    w, h = size
    span = span or h
    column = Image.new("RGB", (1, max(1, h)))
    for y in range(column.height):
        t = (y + 0.5 - top) / float(span)
        t = min(1.0, max(0.0, t))
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                a, b = _rgb(c0), _rgb(c1)
                column.putpixel((0, y), tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3)))
                break
    return column.resize((max(1, w), max(1, h)), Image.NEAREST)


def wordmark(mark, scale=1.0, suffix=None, accent=theme.OK):
    """The site's wordmark (style.css .logo) at `mark` CSS pixels, as the site's header draws it: OPEN small and spaced
    out above, its skewed bar running grey into the accent to DMTQ's end, DMTQ in chrome with the Q lit in the accent,
    and an optional suffix (the site's .s: ADMIN, here PC) at DMTQ's lower right. Returns an RGBA picture.

    The places come from the stylesheet and the face's own metrics (ascent 1.135 em, descent 0.439 em), as a browser
    sets them: OPEN at 0.34 em with 0.2 em spacing and margins 0.72 em left, 0.5 em right, 0.28 em under it; its bar
    0.34 of OPEN's size thick after a 0.42 em gap; DMTQ at 1 em in a 0.94 em line; the suffix at 0.52 em, 8 px after.
    """
    k = SS
    m = mark * scale * k                       # the mark's size in the drawing's pixels
    big = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(1, int(round(m))))
    o_size = 0.34 * m
    small = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(1, int(round(o_size))))
    asc, desc = 1.135, 0.439                   # the face's ascent and descent, in its em
    # Column 1: DMTQ's width (its advances, -0.01 em spacing a letter, 0.14 em room for the lean) sets it.
    m_width = big.getlength("DMTQ") - 0.04 * m + 0.14 * m
    gap = 8 * scale * k                        # the grid's column gap, in pixels whatever the size
    s_size = 0.52 * m
    s_font = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(1, int(round(s_size)))) if suffix else None
    s_width = (s_font.getlength(suffix) + 0.02 * s_size * len(suffix)) if suffix else 0
    row1 = o_size + 0.28 * o_size              # OPEN's line (line-height 1) and its margin under it
    row2 = 0.94 * m                            # DMTQ's line
    width = int(math.ceil(m_width + (gap + s_width + 0.1 * m if suffix else 0)))
    height = int(math.ceil(row1 + row2 + 0.12 * m))   # room under the line for the Q's tail
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # OPEN: its baseline where a 1-high line puts it, letter by letter with its spacing after each.
    o_base = (o_size - (asc + desc) * o_size) / 2 + asc * o_size
    x = 0.72 * o_size
    for ch in "OPEN":
        draw.text((x, o_base), ch, font=small, fill=(0xf4, 0xf6, 0xf8, 255), anchor="ls")
        x += small.getlength(ch) + 0.2 * o_size
    # The bar: from OPEN's end and the gap to column 1's end less OPEN's right margin, centred on OPEN's line, skewed
    # -14 degrees about its middle (its top further right).
    left, right = x + 0.42 * o_size, m_width - 0.5 * o_size
    thick = 0.34 * o_size
    mid = o_size / 2
    lean = thick / 2 * math.tan(math.radians(14))
    bar = Image.new("L", (width, height), 0)
    ImageDraw.Draw(bar).polygon([(left + lean, mid - thick / 2), (right + lean, mid - thick / 2),
                                 (right - lean, mid + thick / 2), (left - lean, mid + thick / 2)], fill=255)
    ramp = Image.linear_gradient("L").rotate(90, expand=True).resize((max(1, int(right - left)), height))
    tint = Image.new("RGBA", (width, height), _rgb("#8f99a4") + (255,))
    tint.paste(Image.composite(Image.new("RGBA", ramp.size, _rgb(accent) + (255,)),
                               Image.new("RGBA", ramp.size, _rgb("#8f99a4") + (255,)), ramp), (int(left), 0))
    tint.paste(_rgb(accent) + (255,), (int(right), 0, width, height))
    img.paste(tint, (0, 0), bar)
    # DMTQ: in a 0.94 em line under row 1, its baseline where that line puts it; DMT in chrome, the Q lit.
    m_top = row1
    m_base = m_top + (row2 - (asc + desc) * m) / 2 + asc * m
    letters = Image.new("L", (width, height), 0)
    q_mask = Image.new("L", (width, height), 0)
    x = 0
    for ch in "DMTQ":
        ImageDraw.Draw(q_mask if ch == "Q" else letters).text((x, m_base), ch, font=big, fill=255, anchor="ls")
        x += big.getlength(ch) - 0.01 * m
    chrome = _vertical((width, height), WORDMARK_CHROME, top=m_top, span=row2).convert("RGBA")
    img.paste(chrome, (0, 0), letters)
    # The Q's own box is its inline box: the face's ascent and descent around its baseline, white into the accent at 60 %.
    q_top = m_base - asc * m
    lit = _vertical((width, height), ((0.0, "#ffffff"), (0.6, accent), (1.0, accent)), top=q_top,
                    span=(asc + desc) * m).convert("RGBA")
    img.paste(lit, (0, 0), q_mask)
    if suffix:
        # The suffix at row 2's foot (0.06 em above it), after column 1 and the gap, in the accent.
        s_top = m_top + row2 - 0.06 * s_size - s_size
        s_base = s_top + (s_size - (asc + desc) * s_size) / 2 + asc * s_size
        x = m_width + gap
        for ch in suffix:
            draw.text((x, s_base), ch, font=s_font, fill=_rgb(accent) + (255,), anchor="ls")
            x += s_font.getlength(ch) + 0.02 * s_size
    return img.resize((max(1, width // k), max(1, height // k)), Image.LANCZOS)


def version_block(label, version, scale=1.0, accent=theme.OK):
    """The version as the site's front page sets it beside the wordmark (style.css .server-ver): a slanted line in the
    accent, a small label in the leaning wide face over the number in the wide face. Returns an RGBA picture."""
    k = SS
    s = scale * k
    label_font = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(1, int(round(12 * s))))
    number_font = ImageFont.truetype(theme.WIDE_FILE, max(1, int(round(16 * s))))
    pad_left, gap_y, pad_bottom = 12 * s, 4 * s, 2 * s
    spacing = 0.08 * 12 * s
    label_w = sum(label_font.getlength(ch) + spacing for ch in label)
    number_w = number_font.getlength(version)
    label_h = 12 * s
    number_h = 16 * s
    # Room after the label for its last letter's lean, which goes past its advance.
    width = int(math.ceil(pad_left + max(label_w + 0.3 * 12 * s, number_w) + 4 * s))
    height = int(math.ceil(label_h + gap_y + number_h + pad_bottom + 2 * s))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # The line: 2 px, from 2 px down to the foot, leaning as the wordmark does.
    line_w, top, bottom = 2 * s, 2 * s, height - pad_bottom
    lean = (bottom - top) / 2 * math.tan(math.radians(14))
    mid_x = line_w / 2 + lean
    shape = Image.new("L", (width, height), 0)
    ImageDraw.Draw(shape).polygon([(mid_x + lean, top), (mid_x + lean + line_w, top), (mid_x - lean + line_w, bottom),
                                   (mid_x - lean, bottom)], fill=255)
    img.paste(Image.new("RGBA", (width, height), _rgb(accent) + (255,)), (0, 0), shape)
    # The label in light grey, spaced out; the number white under it.
    x = pad_left + 2 * lean
    for ch in label:
        draw.text((x, label_h), ch, font=label_font, fill=_rgb("#d7dde4") + (255,), anchor="ls")
        x += label_font.getlength(ch) + spacing
    draw.text((pad_left + lean, label_h + gap_y + number_h), version, font=number_font, fill=(255, 255, 255, 255),
              anchor="ls")
    return img.resize((max(1, width // k), max(1, height // k)), Image.LANCZOS)


def brand(scale=1.0, version="", mark=26, label="PC CLIENT"):
    """The header's left end: the wordmark, and the version block beside it standing on the same line, as the site's
    front page sets its version; the block's label says what this is (PC CLIENT), so the wordmark carries no suffix.
    Returns an RGBA picture."""
    logo = wordmark(mark, scale)
    block = version_block(label, version, scale) if version else None
    if block is None:
        return logo
    gap = int(round(16 * scale))
    width = logo.width + gap + block.width
    height = max(logo.height, block.height)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # Both stand on the picture's foot (the Q's tail room under the wordmark's line lifts the block a little with it).
    tail = int(round(0.12 * mark * scale))
    img.paste(logo, (0, height - logo.height), logo)
    img.paste(block, (logo.width + gap, height - block.height - tail), block)
    return img


# ------------------------------------------------------------------------------------------------- the page behind

# The site's shards at the page's edges (style.css .facets): each (opacity, points) in a 1440 x 900 box, stretched to the
# page's width and kept 900 CSS pixels tall, every one fading out downwards.
FACETS = ((0.75, ((1440, 60), (1330, 0), (1440, 0))),
          (0.62, ((1290, 70), (1440, 250), (1440, 420), (1345, 300))),
          (0.34, ((1345, 300), (1440, 420), (1440, 670), (1400, 480))),
          (0.72, ((0, 250), (112, 470), (0, 425))),
          (0.30, ((0, 425), (112, 470), (176, 900), (0, 900))),
          (0.16, ((1400, 480), (1440, 670), (1440, 900), (1344, 900))))


def _mix(a, b, k):
    """Colour a with k of colour b over it (0: a, 1: b), as hex."""
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * k)) for x, y in zip(ra, rb))


def _half_plane(box, normal, limit):
    """The part of the rectangle `box` (w, h) where the point's projection on `normal` is below `limit`: a polygon."""
    w, h = box
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    inside = lambda p: p[0] * normal[0] + p[1] * normal[1] < limit  # noqa: E731
    out = []
    for a, b in zip(corners, corners[1:] + corners[:1]):
        pa, pb = a[0] * normal[0] + a[1] * normal[1], b[0] * normal[0] + b[1] * normal[1]
        if inside(a):
            out.append(a)
        if inside(a) != inside(b):
            t = (limit - pa) / (pb - pa)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


# The page's top as backdrop() last drew it, for the last few widths and looks: the header and the page area take their
# rows from it each time they are drawn again (the page moved off its top and back, another page, the guide's next
# step), instead of drawing the shards again, which takes a good part of a second at 200 %. A few only: at 200 % one is
# about 13 MB, and the window draws from two (the header's width and the page area's).
TOPS_KEPT = 4
# Key (width, scale, accent, reach of the light) -> the picture of the page's first rows, the newest last.
_tops = collections.OrderedDict()


def backdrop(width, height, scale=1.0, accent=theme.OK, offset=0, top=None):
    """The page behind the cards, as the site's: its field with the faint perforated metal all over, two pale panes and
    the accent's light at the top (body::before), and the green shards at the left and right edges (.facets).

    The picture is the part of the page from `offset` down, `height` tall: the header draws the page's top and the
    page area the rest, and they meet without a seam. `top` is how far down the page the panes and the light reach
    before they have faded (the site's 620 px; less when the cards would cover them anyway).

    The rows the light and the shards reach are cut from the page's top as drawn once for this width and look (_top);
    the rows under them are the field alone. Either way the picture is the one _whole() draws, pixel for pixel.
    """
    width, height = max(1, int(width)), max(1, int(height))
    offset = max(0, int(offset))
    top_h = int(top if top is not None else 620 * scale)
    # How far down the page anything but the field reaches: the light, and the shards' 900 CSS pixels.
    reach = max(top_h, int(900 * scale))
    if offset >= reach:
        # All of it under the top: the field and its dots, which cost little to draw.
        return _field(width, height, scale, offset)
    whole = _top(width, scale, accent, top_h, reach)
    if offset + height <= reach:
        # All of it in the top: its rows, as a picture of its own (the caller may draw on it).
        return whole.crop((0, offset, width, offset + height))
    # The top's rows from `offset` down, then the field for the rest, its dots on the same grid.
    img = Image.new("RGB", (width, height))
    img.paste(whole.crop((0, offset, width, reach)), (0, 0))
    img.paste(_field(width, offset + height - reach, scale, reach), (0, reach - offset))
    return img


def _top(width, scale, accent, top_h, reach):
    """The page's first `reach` rows drawn whole, kept for the next picture of the same width and look."""
    key = (width, scale, accent, top_h)
    # Taken out and put back last: the one used longest ago goes first.
    found = _tops.pop(key, None)
    if found is None:
        found = _whole(width, reach, scale, accent, 0, top_h)
    _tops[key] = found
    while len(_tops) > TOPS_KEPT:
        # The oldest goes, so the kept pictures never hold more than a few widths' worth.
        _tops.popitem(last=False)
    return found


def _field(width, height, scale, offset):
    """The page's field with its dots: one in each 6 px square, white at 4.5 %, on the page's own grid whatever part
    of the page this is (`offset` rows from its top)."""
    img = Image.new("RGB", (width, height), _rgb(theme.BG))
    step = max(4, int(round(6 * scale)))
    # One dot in its square, then a row of squares across, lit on the field's colour once.
    tile = Image.new("L", (step, step), 0)
    ImageDraw.Draw(tile).ellipse([step / 2 - scale, step / 2 - scale, step / 2 + scale, step / 2 + scale], fill=11)
    strip = Image.new("L", (width, step), 0)
    for x in range(0, width, step):
        strip.paste(tile, (x, 0))
    row = Image.new("RGB", (width, step), _rgb(theme.BG))
    row.paste((255, 255, 255), (0, 0), strip)
    # Then that row copied down from the grid's line above the picture: the same pixels as lighting each row on its own,
    # for a fraction of the work.
    for y in range(-(offset % step), height, step):
        img.paste(row, (0, y))
    return img


def _whole(width, height, scale, accent, offset, top_h):
    """The page's picture from `offset` down, every layer drawn for every row: the field, the lit top while `offset`
    is above `top_h`, the shards in the first 900 CSS pixels. backdrop() keeps its top; the tests compare the two."""
    img = _field(width, height, scale, offset)
    # The top: full to 45 % of its reach, then fading; drawn whole, the part in this picture kept.
    if offset < top_h:
        fade = Image.new("L", (1, top_h), 0)
        for y in range(top_h):
            t = y / float(max(1, top_h))
            fade.putpixel((0, y), 255 if t < 0.45 else int(255 * max(0.0, (1 - t) / 0.55)))
        fade = fade.resize((width, top_h))
        panes = Image.new("L", (width, top_h), 0)
        draw = ImageDraw.Draw(panes)
        # 115 degrees from the top-left corner, light up to 22 % of the way; 245 degrees from the top-right, up to 16 %.
        # The panes' geometry is the site's 620 px top, whatever the reach of their light.
        full = int(620 * scale)
        for angle, alpha, share, from_right in ((115, 14, 0.22, False), (245, 10, 0.16, True)):
            rad = math.radians(angle)
            normal = (math.sin(rad), -math.cos(rad))
            length = abs(width * normal[0]) + abs(full * normal[1])
            origin = (width, 0) if from_right else (0, 0)
            limit = share * length + origin[0] * normal[0]
            polygon = _half_plane((width, top_h), normal, limit)
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=alpha)
        light = Image.composite(panes, Image.new("L", panes.size, 0), fade)
        band = Image.new("RGB", (width, top_h), (255, 255, 255))
        # The accent's light from above the middle: an ellipse 70 % wide, at 12 % in its middle.
        glow = Image.radial_gradient("L").resize((max(1, int(width * 1.4)), max(1, int(full * 2))))
        glow = glow.point(lambda v: int(30 * max(0.0, 1 - (v / 255.0) / 0.7)))
        sheet = Image.new("L", (width, top_h), 0)
        sheet.paste(glow, (int(width / 2 - glow.width / 2), int(-0.2 * full - glow.height / 2)))
        sheet = Image.composite(sheet, Image.new("L", sheet.size, 0), fade)
        rows = (offset, min(top_h, offset + height))
        region = img.crop((0, 0, width, rows[1] - rows[0]))
        region.paste(band.crop((0, rows[0], width, rows[1])), (0, 0), light.crop((0, rows[0], width, rows[1])))
        region.paste(_rgb(accent), (0, 0), sheet.crop((0, rows[0], width, rows[1])))
        img.paste(region, (0, 0))
    # The shards, 900 px tall from the page's top: drawn twice as large and scaled down, smooth along their edges.
    span = int(900 * scale)
    if offset < span:
        k = 2
        mask = Image.new("L", (width * k, span * k), 0)
        for opacity, points in FACETS:
            layer = Image.new("L", mask.size, 0)
            ImageDraw.Draw(layer).polygon([(x / 1440.0 * width * k, y / 900.0 * span * k) for x, y in points],
                                          fill=int(255 * opacity))
            mask = Image.composite(layer, mask, layer)
        mask = mask.resize((width, span), Image.LANCZOS)
        down = Image.linear_gradient("L").resize((1, span)).point(lambda v: 255 - v)
        mask = Image.composite(mask, Image.new("L", mask.size, 0), down.resize((width, span)))
        colour = _vertical((width, span), ((0.0, _mix(accent, "#ffffff", 0.12)), (1.0, _mix(accent, "#000000", 0.30))))
        rows = (offset, min(span, offset + height))
        part = img.crop((0, 0, width, rows[1] - rows[0]))
        part.paste(colour.crop((0, rows[0], width, rows[1])), (0, 0), mask.crop((0, rows[0], width, rows[1])))
        img.paste(part, (0, 0))
    return img


def page_title(text, scale=1.0, size=42, accent=theme.OK):
    """A page's name as the site's masthead sets it: the leaning wide face, white at its top into the accent at its
    foot (#fff 8 %, the accent 72 %, over a 1.08 line). A title with Hangul in it (the guide's questions in Korean) is
    set in Pretendard Bold, which has it, leant as the wide face leans. Returns an RGBA picture and its baseline."""
    k = SS
    t = size * scale * k
    # The wide face has no Hangul (the syllables 가 to 힣): a Korean title takes Pretendard Bold for all of it, its Latin
    # letters too.
    hangul = any("가" <= ch <= "힣" for ch in text)
    if hangul:
        # Hangul stands taller than the wide face's capitals at one size: a little smaller, the same height on the page.
        t = t * 0.86
    font = ImageFont.truetype(theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_ITALIC_FILE, max(1, int(round(t))))
    # Each face's ascent and descent in ems, which place the baseline in the 1.08 line.
    asc, desc = (1.0, 0.3) if hangul else (1.135, 0.439)
    line = 1.08 * t
    base = (line - (asc + desc) * t) / 2 + asc * t
    # Room after the last letter for its lean and the 0.12 em the site keeps, and under the line for nothing.
    width = int(math.ceil(font.getlength(text) - 0.012 * t * len(text) + 0.3 * t))
    height = int(math.ceil(line))
    letters = Image.new("L", (width, height), 0)
    x = 0
    for ch in text:
        ImageDraw.Draw(letters).text((x, base), ch, font=font, fill=255, anchor="ls")
        x += font.getlength(ch) - 0.012 * t
    if hangul:
        # Pretendard stands upright: sheared as the wide face leans (its top a fifth of its height to the right), the
        # picture wider by that much so that the last letter's top keeps its room.
        lean = 0.2
        letters = letters.transform((width + int(lean * height), height), Image.AFFINE,
                                    (1, lean, -lean * height, 0, 1, 0), resample=Image.BICUBIC)
        width = letters.width
    colour = _vertical((width, height), ((0.0, "#ffffff"), (0.08, "#ffffff"), (0.72, accent), (1.0, accent)),
                       span=height).convert("RGBA")
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    img.paste(colour, (0, 0), letters)
    return img.resize((max(1, width // k), max(1, height // k)), Image.LANCZOS), int(round(base / k))


def numeral(text, colour, scale=1.0, size=34, bg=theme.BG):
    """A step's number as the site's steps set it (.steps li::before): big, leaning, in one colour. On `bg`."""
    k = SS
    t = size * scale * k
    font = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(1, int(round(t))))
    asc = 1.135
    # The figure's own height (its capitals' 0.69 em) and a little room above and under it.
    top, base = int(asc * t - 0.74 * t), int(asc * t)
    width = int(math.ceil(font.getlength(text) + 0.25 * t))
    height = int(math.ceil(0.84 * t))
    # On a plain colour, or on nothing (bg None) to lie over a picture.
    img = Image.new("RGB", (width, height), _rgb(bg)) if bg else Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fill = _rgb(colour) + (() if bg else (255,))
    ImageDraw.Draw(img).text((0, base - top + 0.04 * t), text, font=font, fill=fill, anchor="ls")
    return img.resize((max(1, width // k), max(1, height // k)), Image.LANCZOS)


def lamp(colour, scale=1.0, bg=None, hollow=False):
    """A state's small light, as the site's (.state i): a 7 px dot with a soft glow of its colour around it. On `bg`
    when given (an opaque picture), else on nothing. `hollow`: a ring with half the glow, for what will change rather
    than what is fine or wrong, so that the shape says it as well as the colour."""
    d = 7 * scale
    reach = 7 * scale
    size = int(math.ceil(d + 2 * reach))
    k = SS
    glow = Image.new("L", (size * k, size * k), 0)
    c = size * k / 2.0
    ImageDraw.Draw(glow).ellipse([c - d * k / 2, c - d * k / 2, c + d * k / 2, c + d * k / 2], fill=140)
    glow = glow.filter(ImageFilter.GaussianBlur(reach * k / 2.5)).resize((size, size), Image.LANCZOS)
    dot = Image.new("L", (size * k, size * k), 0)
    ImageDraw.Draw(dot).ellipse([c - d * k / 2, c - d * k / 2, c + d * k / 2, c + d * k / 2], fill=255)
    if hollow:
        # The dot's middle taken out, a ring 1.6 px thick at 100 % left; its glow halved, so that it reads quieter
        # than a lit dot beside it.
        r = d * k / 2 - 1.6 * scale * k
        ImageDraw.Draw(dot).ellipse([c - r, c - r, c + r, c + r], fill=0)
        glow = glow.point(lambda v: v // 2)
    dot = dot.resize((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), _rgb(bg) + (255,) if bg else (0, 0, 0, 0))
    img.paste(_rgb(colour) + (255,), (0, 0), glow)
    img.paste(_rgb(colour) + (255,), (0, 0), dot)
    return img


def tab_face(width, height, state, scale=1.0, bg=theme.PANEL):
    """One choice of a row of tabs, as the site's (.tabs a): a trapezoid, its top 11 px shorter at each end, in rail
    metal, lighter under the pointer, filled with the accent when chosen. On `bg` around its slanted sides."""
    k = SS
    w, h = width * k, height * k
    slant = 11 * scale * k
    fill = {"on": theme.OK, "hover": theme.RAIL_UP, "normal": theme.RAIL}[state]
    img = Image.new("RGB", (w, h), _rgb(bg))
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).polygon([(slant, 0), (w - slant, 0), (w, h), (0, h)], fill=255)
    img.paste(_rgb(fill), (0, 0), shape)
    # Its depth, drawn at the picture's own scale: the choices raised, the chosen one sunk (pressed in).
    if state == "on":
        sunk(img, shape, scale * k, fill, depth=2)
    else:
        raised(img, shape, scale * k, fill)
    return img.resize((width, height), Image.LANCZOS)


def play_button(width, height, state="normal", scale=None):
    """The PLAY button: a lime slab with its corners cut at 45 degrees, the site's main button in the game's shape;
    raised while it can be pressed, sunk while it is held, flat while it waits or the game plays. `scale`: the screen's
    (its 50 logical pixels of height by default)."""
    scale = scale or height / 50.0
    w, h = width * SS, height * SS
    cut = int(h * 0.28)
    top, bottom = {
        "normal": ("#b2f777", theme.OK),
        "hover": ("#c6fa98", "#9df55a"),
        "pressed": (theme.OK, "#6fcf22"),
        "disabled": ("#262d37", "#1d232b"),
        "playing": ("#2c3646", "#222a36"),
    }[state]
    # A vertical gradient, then the cut-corner outline as its mask (the picture's own transparency).
    grad = Image.linear_gradient("L").resize((w, h))
    body = Image.composite(Image.new("RGB", (w, h), _rgb(bottom)), Image.new("RGB", (w, h), _rgb(top)), grad)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(cut_outline(0, 0, w, h, cut), fill=255)
    if state in ("normal", "hover"):
        # A thin bright edge along the top, the chrome highlight, and the slab raised.
        edge = Image.new("L", (w, h), 0)
        ImageDraw.Draw(edge).line([(cut, SS), (w - SS, SS)], fill=150, width=SS)
        body.paste((255, 255, 255), (0, 0), edge)
        raised(body, mask, scale * SS, bottom)
    elif state == "pressed":
        sunk(body, mask, scale * SS, bottom, depth=4)
    img = body.convert("RGBA")
    img.putalpha(mask)
    return img.resize((width, height), Image.LANCZOS)


# The room round a switch's pill for the accent's faint ring when it is on (pixels, whatever the scale).
TOGGLE_HALO = 3


def toggle(on, width, height, enabled=True, colour=None, knob=None, bg=theme.BG):
    """An on/off switch as the site's (.screen-switch): a pill in the accent with a faint ring of it around, a dark knob
    at its right end; off, rail metal with a light knob at its left end. The picture is the ring's 3 px wider on every
    side, on `bg`."""
    k = SS
    ring = TOGGLE_HALO
    w, h = (width + 2 * ring) * k, (height + 2 * ring) * k
    colour = colour or theme.OK
    img = Image.new("RGB", (w, h), _rgb(bg))
    r = height * k / 2.0
    x0, y0, x1, y1 = ring * k, ring * k, ring * k + width * k, ring * k + height * k
    if on and enabled:
        halo = Image.new("L", (w, h), 0)
        ImageDraw.Draw(halo).rounded_rectangle([0, 0, w - 1, h - 1], radius=r + ring * k, fill=int(255 * 0.35))
        img.paste(_rgb(colour), (0, 0), halo)
    track = Image.new("L", (w, h), 0)
    ImageDraw.Draw(track).rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r, fill=255)
    fill = colour if on and enabled else theme.RAIL_UP
    img.paste(_rgb(fill), (0, 0), track)
    # The track sunk into the card (the switch's scale: 22 logical pixels of height).
    scale = height / 22.0
    sunk(img, track, scale * k, fill, depth=2, across=False)
    # The knob: 16 of 22, 3 from the end, standing on the track: a soft shadow under it, then the knob raised.
    kd = (height - 6) * k
    kx = x1 - 3 * k - kd if on else x0 + 3 * k
    ky = y0 + 3 * k
    dot = Image.new("L", (w, h), 0)
    ImageDraw.Draw(dot).ellipse([kx, ky, kx + kd, ky + kd], fill=255)
    under = _moved(dot, 0, max(1, int(round(scale * k)))).filter(ImageFilter.GaussianBlur(scale * k))
    img.paste((0, 0, 0), (0, 0), _at(ImageChops.multiply(under, track), 0.5))
    knob_fill = knob or ("#0c0f13" if on and enabled else theme.MUTED)
    img.paste(_rgb(knob_fill), (0, 0), dot)
    raised(img, dot, scale * k, knob_fill)
    return img.resize((width + 2 * ring, height + 2 * ring), Image.LANCZOS)


def knob(size, colour=theme.TEXT, ring=theme.OK, scale=None):
    """A slider knob: a light disc with a ring in the accent (the site's lime), raised off the track. `scale`: the
    screen's (its 18 logical pixels by default)."""
    scale = scale or size / 18.0
    s = size * SS
    disc = Image.new("L", (s, s), 0)
    ImageDraw.Draw(disc).ellipse([0, 0, s - 1, s - 1], fill=255)
    body = Image.new("RGB", (s, s), _rgb(ring))
    inset = int(s * 0.22)
    ImageDraw.Draw(body).ellipse([inset, inset, s - 1 - inset, s - 1 - inset], fill=_rgb(colour))
    raised(body, disc, scale * SS, ring)
    img = body.convert("RGBA")
    img.putalpha(disc)
    return img.resize((size, size), Image.LANCZOS)


def slider_track(width, height, fraction, colour, scale=1.0, bg=theme.PANEL):
    """A slider's track, let into the card it lies on: a rounded groove in rail metal, its part up to `fraction` in
    `colour`, a soft shadow inside its top. On `bg`."""
    k = SS
    w, h = width * k, height * k
    img = Image.new("RGB", (w, h), _rgb(bg))
    groove = Image.new("L", (w, h), 0)
    ImageDraw.Draw(groove).rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=255)
    img.paste(_rgb(theme.RAIL), (0, 0), groove)
    done = int(round(max(0.0, min(1.0, fraction)) * (w - 1)))
    if done >= h:
        lit = Image.new("L", (w, h), 0)
        ImageDraw.Draw(lit).rounded_rectangle([0, 0, done, h - 1], radius=h // 2, fill=255)
        img.paste(_rgb(colour), (0, 0), lit)
    sunk(img, groove, scale * k, theme.RAIL, depth=2, across=False)
    return img.resize((width, height), Image.LANCZOS)


# A field's edges, as a recess in the card: dark along its top and left, catching the light along its foot and right;
# brighter edges under the pointer, the accent all round while it is typed in (the site's .input:focus).
FIELD_EDGES = {"normal": ("#06080b", "#3d4651"), "hover": ("#06080b", "#55606c"), "focus": (theme.OK, theme.OK),
               "disabled": ("#0b0e12", "#272e36")}


def field_face(width, height, state="normal", scale=1.0, bg=theme.PANEL):
    """A text field's (or a drop-down's) face: the site's dark field let into its card, one pixel of edge round it
    (FIELD_EDGES), darker at its top, with a soft shadow inside its top and left edges. `state`: normal, hover, focus or
    disabled."""
    k = SS
    w, h = width * k, height * k
    # The well in the field's own colour (the entry's words sit on the same colour in its middle), its shadow inside
    # its top and left edges.
    img = Image.new("RGB", (w, h), _rgb(theme.FIELD))
    box = Image.new("L", (w, h), 255)
    sunk(img, box, scale * k, theme.FIELD, depth=3)
    # The edge: one pixel (two at 200 %), its top and left in one colour, its foot and right in the other.
    e = max(1, int(round(scale))) * k
    dark, light = FIELD_EDGES[state]
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, h - e, w - 1, h - 1], fill=_rgb(light))
    draw.rectangle([w - e, 0, w - 1, h - 1], fill=_rgb(light))
    draw.rectangle([0, 0, w - 1, e - 1], fill=_rgb(dark))
    draw.rectangle([0, 0, e - 1, h - 1], fill=_rgb(dark))
    return img.resize((width, height), Image.LANCZOS)


def chevron(width, height, colour, scale=1.0):
    """A drop-down's arrow: a small chevron pointing down, in `colour`, on nothing (a picture with transparency)."""
    k = SS
    w, h = width * k, height * k
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # 8 by 4.5 logical pixels round the middle, 1.6 thick.
    half, drop = 4 * scale * k, 2.25 * scale * k
    cx, cy = w / 2.0, h / 2.0
    ImageDraw.Draw(img).line([(cx - half, cy - drop), (cx, cy + drop), (cx + half, cy - drop)],
                             fill=_rgb(colour) + (255,), width=max(k, int(round(1.6 * scale * k))), joint="curve")
    return img.resize((width, height), Image.LANCZOS)


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
    """What shows behind a dialog: the window blurred and dimmed, with the card's shadow under it.

    `window` is the window as a picture (snapshot.py) and `box` the card's (x, y, width, height) in it. Returns the
    scene and the blurred window before dimming, which the card's glass is made from.
    """
    w, h = window.size
    soft = _soft(window, 9 * scale)
    scene = Image.blend(soft, Image.new("RGB", (w, h), _rgb(theme.BG)), 0.58)
    x, y, bw, bh = box
    # The shadow is only blurred near the card: a blur over the whole window would cost much more.
    reach = int(40 * scale)
    area = (max(0, x - reach), max(0, y - reach), min(w, x + bw + reach), min(h, y + bh + reach + int(12 * scale)))
    size = (area[2] - area[0], area[3] - area[1])
    mask = Image.new("L", size, 0)
    outline = card_outline(x - area[0], y - area[1] + int(12 * scale), bw, bh, cut)
    ImageDraw.Draw(mask).polygon(outline, fill=int(255 * 0.72))
    mask = mask.filter(ImageFilter.GaussianBlur(20 * scale))
    region = scene.crop(area)
    region.paste(Image.new("RGB", size, (0, 0, 0)), (0, 0), mask)
    scene.paste(region, area[:2])
    return scene, soft


def dialog_panel(scene, soft, box, cut, scale):
    """The card a dialog is: the site's frosted gunmetal over the blurred window (86 %), a sheen at its head and a faint
    light along its top edge, the top-right corner cut. Returns an opaque picture of the box."""
    x, y, bw, bh = box
    panel = scene.crop((x, y, x + bw, y + bh))
    glass = Image.blend(soft.crop((x, y, x + bw, y + bh)), Image.new("RGB", (bw, bh), _rgb(theme.PANEL)), 0.86)
    reach = max(1, int(240 * scale))
    sheen = Image.linear_gradient("L").resize((1, reach)).point(lambda v: int(14 * (1 - v / 255.0) ** 1.6))
    glass.paste(Image.new("RGB", (bw, min(reach, bh)), (255, 255, 255)), (0, 0), sheen.resize((bw, reach)).crop(
        (0, 0, bw, min(reach, bh))))
    shape = _mask((bw, bh), lambda d, s: d.polygon(card_outline(0, 0, bw * s, bh * s, cut * s), fill=255))
    panel.paste(glass, (0, 0), shape)
    # The rim: white at 10 % along the top edge, as the site's glass (inset 0 1px rgba(255,255,255,.1)).
    rim = _mask((bw, bh), lambda d, s: d.line([(0, 0), ((bw - cut) * s, 0)], fill=26, width=s))
    panel.paste(Image.new("RGB", (bw, bh), (255, 255, 255)), (0, 0), rim)
    return panel


# A button's colours for each look, as the site's: each state's fill (one colour, or the colours down it), and its
# words. Lit buttons (.button, .btn-primary) in the accent's gradient with dark words; the rest quiet metal (.btn) or
# the red of removing (.btn-danger). None has an edge.
_OFF = (theme.RAIL,)
BUTTON_LOOKS = {
    "neutral": {"normal": (theme.RAIL_UP,), "hover": ("#414b57",), "pressed": (theme.RAIL,), "disabled": _OFF,
                "text": theme.TEXT},
    "danger": {"normal": ("#ff8592", theme.BAD, "#e04558"), "hover": ("#ff9ba6", "#ff7484", theme.BAD),
               "pressed": (theme.BAD, "#ea4d60", "#e04558"), "disabled": _OFF, "text": "#2b0409"},
    "warn": {"normal": ("#ffdc6e", theme.WARN, "#e0b22a"), "hover": ("#ffe48d", "#ffd556", theme.WARN),
             "pressed": (theme.WARN, "#e0b22a", "#c99c1e"), "disabled": _OFF, "text": theme.INK},
    "home": {"normal": ("#acf673", theme.OK, "#76cb33"), "hover": ("#bcf98c", "#9df55a", "#82d83c"),
             "pressed": ("#9ee665", "#7fe234", "#6bb92e"), "disabled": _OFF, "text": "#0d1c04"},
    # Removing or starting over: metal with a red tint and pale red words, filled red under the pointer.
    "danger_quiet": {"normal": ("#4e3741",), "hover": (theme.BAD,), "pressed": ("#e04558",), "disabled": _OFF,
                     "text": "#ffb3bc", "hover_text": "#2b0409"},
}


# ------------------------------------------------------------------------------------------------ depth
#
# What can be pressed stands a little out of its surface and sinks when pressed, and what takes typing is sunk into it
# (the owner's neumorphism, kept to the game's dark plates and cut corners): a raised face has a line of light along
# its top and left edges and a shade along its foot and right; a sunk one a soft shadow inside its top and left edges and
# a faint light inside its foot. Both are drawn inside the face's own outline, so a pressable keeps its size and its
# place, and its words their colour on its fill.


def _moved(mask, dx, dy, edge=0):
    """The mask moved by (dx, dy) pixels; what comes in from beyond the picture's edge is `edge` (255: the outside)."""
    out = Image.new("L", mask.size, edge)
    out.paste(mask, (dx, dy))
    return out


def _at(mask, strength):
    """The mask at `strength` (0 to 1) of its own."""
    return mask.point(lambda v: int(v * strength))


def _bright(colour):
    """Whether a fill is a bright one (the lime, the yellow, the red of a lit button) rather than the metal."""
    r, g, b = _rgb(colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 110


def raised(img, shape, scale, fill):
    """`img` with the face in `shape` (a mask) raised: light along its top and left edges, shade along its foot and
    right, each a pixel wide at 100 % (two at 200 %), stronger light on the metal than on a lit fill."""
    k = max(1, int(round(scale)))
    top = ImageChops.subtract(shape, _moved(shape, k, k))
    foot = ImageChops.subtract(shape, _moved(shape, -k, -k))
    light, shade = (0.42, 0.22) if _bright(fill) else (0.17, 0.45)
    img.paste((255, 255, 255), (0, 0), _at(top, light))
    img.paste((0, 0, 0), (0, 0), _at(foot, shade))
    return img


def sunk(img, shape, scale, fill, depth=3, across=True):
    """`img` with the face in `shape` sunk: a soft shadow inside its top and left edges, `depth` pixels at 100 %, and a
    faint light inside its foot, as a pressed button or a field let into its surface. `across` False keeps the shadow
    to the top (a groove or a switch's pill, whose round ends would otherwise start a little later than they are)."""
    d = max(1, int(round(depth * scale)))
    k = max(1, int(round(scale)))
    # The outside, moved down (and right) into the face: what of it lies inside along the top (and left), softened.
    outside = ImageChops.invert(shape)
    shadow = _moved(outside, d if across else 0, d, edge=255).filter(ImageFilter.GaussianBlur(max(1.0, d * 0.6)))
    shadow = ImageChops.multiply(shadow, shape)
    img.paste((0, 0, 0), (0, 0), _at(shadow, 0.34 if _bright(fill) else 0.55))
    foot = ImageChops.subtract(shape, _moved(shape, -k, -k))
    img.paste((255, 255, 255), (0, 0), _at(foot, 0.10 if not _bright(fill) else 0.18))
    return img


def _fill(size, colours):
    """A button's fill: one colour, or a gradient through two or three (top, middle at 55 %, foot) as the site's."""
    if len(colours) == 1:
        return Image.new("RGB", size, _rgb(colours[0]))
    if len(colours) == 2:
        return _gradient(size, *colours)
    return _vertical(size, ((0.0, colours[0]), (0.55, colours[1]), (1.0, colours[2])))


def button_face(size, margin, look, state, focused, scale, under=None, bg=None):
    """A button's picture, cut at two corners as the site's buttons: quiet metal, or lit in a colour.

    `under` is what lies beneath (a dialog's panel pixels) or `bg` a plain colour; `margin` pixels on every side hold
    the focus ring when the button has the keyboard. With no margin (a page's button, which keeps its size) the ring
    runs just inside the outline instead: cyan on metal, the words' dark ink on a coloured fill, where cyan would not
    show.
    """
    colours = BUTTON_LOOKS[look]
    w, h = size
    img = under.copy() if under is not None else Image.new("RGB", size, _rgb(bg or theme.BG))
    bw, bh = w - 2 * margin, h - 2 * margin
    # The site's cut: 8 px on its buttons.
    cut = max(4, int(round(8 * scale)))
    shape = _mask((w, h), lambda d, s: d.polygon(cut_outline(margin * s, margin * s, bw * s, bh * s, cut * s),
                                                 fill=255))
    filled = Image.new("RGB", (w, h))
    filled.paste(_fill((bw, bh), colours[state]), (margin, margin))
    img.paste(filled, (0, 0), shape)
    # Its depth: raised to be pressed, sunk while pressed, flat while it cannot be.
    middle = colours[state][len(colours[state]) // 2]
    if state in ("normal", "hover"):
        raised(img, shape, scale, middle)
    elif state == "pressed":
        sunk(img, shape, scale, middle)
    if focused and not margin:
        # Inside the outline, parallel to it: the cut corners move in by about 0.4 of the inset (45 degrees).
        inset = max(2, int(round(3 * scale)))
        inner_cut = max(1, cut - int(round(inset * 0.4)))
        ring = _mask((w, h), lambda d, s: d.line(
            cut_outline(inset * s, inset * s, (bw - 2 * inset) * s - s, (bh - 2 * inset) * s - s, inner_cut * s)
            + [((inset + inner_cut) * s, inset * s)], fill=255, width=max(2, int(round(2 * scale))) * s))
        if look == "neutral" or (look == "danger_quiet" and state not in ("hover", "pressed")):
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


def corner(size, inside, outside, seam=None):
    """A panel's top-right corner, cut: what covers a card's square corner, the page's colour beyond the cut (a seam
    along the cut when one is given)."""
    k = SS
    s = size * k
    img = Image.new("RGB", (s, s), _rgb(inside))
    cut = Image.new("L", (s, s), 0)
    ImageDraw.Draw(cut).polygon([(0, 0), (s, 0), (s, s)], fill=255)
    img.paste(_rgb(outside), (0, 0), cut)
    if seam:
        line = Image.new("L", (s, s), 0)
        ImageDraw.Draw(line).line([(0, 0), (s, s)], fill=255, width=k)
        img.paste(_rgb(seam), (0, 0), line)
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
