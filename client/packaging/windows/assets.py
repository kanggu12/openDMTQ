"""Make the pictures and the version files the Windows build needs, from the launcher's own drawing code.

  python packaging/windows/assets.py OUT_DIR VERSION      (from client/)

Writes OpenDMTQ.ico (the program and installer icon), splash.png (shown while Velopack updates), setup-splash.png
(shown while the installer unpacks itself), and version-info.txt and setup-version-info.txt (the file properties
Windows shows for the launcher and the installer).
"""

import os
import sys

# Run from client/ (the build mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PIL import ImageDraw, ImageFont  # noqa: E402

from opendmtq_client import art, theme  # noqa: E402


def icon(path):
    """The mark at every size Windows asks for, from 16 to 256 pixels."""
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # Each size is drawn on its own (not scaled from the largest), so small ones stay sharp.
    images = [art.mark(s) for s in sizes]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def splash(path, version, width=720, height=400, scale=1.4, label="TECHNIKA Q"):
    """The picture shown while OpenDMTQ installs or updates: the site's shards, the wordmark in chrome."""
    img = art.shards(width, height, seed=19).convert("RGBA")
    mark = art.logo(int(width * 0.42), scale)
    x, y = int(width * 0.075), int(height * 0.29)
    img.alpha_composite(mark, (x, y))
    small = ImageFont.truetype(theme.WIDE_ITALIC_FILE, max(10, int(round(9.5 * scale))))
    ImageDraw.Draw(img).text((x + int(6 * scale), y + mark.height + int(10 * scale)), "%s  ·  %s" % (label, version),
                             font=small, fill=theme.MUTED)
    img.convert("RGB").save(path)


def version_file(path, version, description="OpenDMTQ launcher for PCs"):
    """PyInstaller's version resource: what Explorer shows under the program's Properties > Details."""
    parts = (version.split("+")[0].split("-")[0].split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(str(int(p)) if p.isdigit() else "0" for p in parts)
    text = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%(n)s), prodvers=(%(n)s), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'OpenDMTQ'),
    StringStruct('FileDescription', '%(d)s'),
    StringStruct('FileVersion', '%(v)s'),
    StringStruct('LegalCopyright', 'MIT License'),
    StringStruct('ProductName', 'OpenDMTQ'),
    StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""" % {"n": numbers, "v": version, "d": description}
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    out, version = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    icon(os.path.join(out, "OpenDMTQ.ico"))
    splash(os.path.join(out, "splash.png"), version)
    splash(os.path.join(out, "setup-splash.png"), version, 560, 312, 1.1, "SETUP")
    version_file(os.path.join(out, "version-info.txt"), version)
    version_file(os.path.join(out, "setup-version-info.txt"), version, "OpenDMTQ setup")


if __name__ == "__main__":
    main()
