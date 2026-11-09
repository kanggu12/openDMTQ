"""Every screenshot of one language on one page, a third of their size, each with its name under it, to look the
whole launcher over at once.

  python tests/ui/sheet.py OUT_DIR LANG      (writes OUT_DIR/sheet-LANG.png)
"""

import os
import sys

from PIL import Image, ImageDraw


def main():
    out, lang = sys.argv[1], sys.argv[2]
    names = sorted(n for n in os.listdir(out) if n.startswith(lang + "-") and n.endswith(".png"))
    if not names:
        print("sheet: no screenshots for %s" % lang)
        return 1
    # Four across, each a third of its size, with room for its name under it.
    thumbs = []
    for name in names:
        img = Image.open(os.path.join(out, name)).convert("RGB")
        img.thumbnail((img.width // 3, img.height // 3))
        thumbs.append((name[:-4], img))
    across = 4
    cell_w = max(t.width for _, t in thumbs) + 16
    cell_h = max(t.height for _, t in thumbs) + 34
    rows = (len(thumbs) + across - 1) // across
    sheet = Image.new("RGB", (across * cell_w, rows * cell_h), (8, 10, 12))
    draw = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(thumbs):
        x, y = (i % across) * cell_w + 8, (i // across) * cell_h + 8
        sheet.paste(img, (x, y))
        draw.text((x, y + img.height + 4), name, fill=(200, 205, 210))
    sheet.save(os.path.join(out, "sheet-%s.png" % lang))
    print("sheet-%s.png: %d screens" % (lang, len(thumbs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
