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

from opendmtq_client import art  # noqa: E402


def icon(path):
    """The mark at every size Windows asks for, from 16 to 256 pixels."""
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # Each size is drawn on its own (not scaled from the largest), so small ones stay sharp.
    images = [art.mark(s) for s in sizes]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def splash(path, version, width=720, height=400, scale=1.75, label="PC CLIENT"):
    """The picture shown while OpenDMTQ installs or updates, as the launcher's own header: the site's page behind, and
    the wordmark with the version block beside it, in the middle."""
    img = art.backdrop(width, height, scale=scale / 1.75).convert("RGBA")
    # The header's brand at a larger size: the wordmark with PC after it, the label over the version.
    brand = art.brand(scale, "v" + version, label=label)
    img.alpha_composite(brand, ((width - brand.width) // 2, (height - brand.height) // 2))
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
    splash(os.path.join(out, "setup-splash.png"), version, 560, 312, 1.375, "SETUP")
    version_file(os.path.join(out, "version-info.txt"), version)
    version_file(os.path.join(out, "setup-version-info.txt"), version, "OpenDMTQ setup")


if __name__ == "__main__":
    main()
