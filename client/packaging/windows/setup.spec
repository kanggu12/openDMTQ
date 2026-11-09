# PyInstaller recipe for OpenDMTQ-Setup.exe: one file holding the installer's dialogs (opendmtq_client/installer.py)
# and Velopack's own setup, which it runs without a window. Run by client/packaging/windows/build.sh inside the Wine
# build container, from client/ in the repository, after vpk has made Velopack's setup.
import os

ROOT = os.path.abspath(".")
BUILD = os.environ.get("OPENDMTQ_BUILD_DIR", os.path.join(ROOT, "build", "windows"))
FONTS = os.path.join(ROOT, "opendmtq_client", "assets", "fonts")
INSIDE = os.path.join("opendmtq_client", "assets", "fonts")

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "setup_entry.py")],
    pathex=[ROOT],
    # Velopack's setup (installer.py finds it next to itself), the fonts the dialogs use with their licences, and the
    # version.
    datas=[(os.environ["OPENDMTQ_VELOPACK_SETUP"], "."), (os.path.join(BUILD, "version.txt"), "opendmtq_client")] + [
        (os.path.join(FONTS, name), INSIDE) for name in (
            "DMTQWide-ExtraBold.ttf", "DMTQWide-ExtraBoldItalic.ttf", "Pretendard-Regular.ttf",
            "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf", "MaterialIcons-Regular.ttf", "Saira-OFL.txt",
            "Pretendard-OFL.txt", "MaterialIcons-LICENSE.txt", "README.md")],
    hiddenimports=["PIL._tkinter_finder"],
    # The installer needs none of the launcher's network or update code.
    excludes=["unittest", "pydoc", "test", "lib2to3", "idlelib", "velopack", "sqlite3", "asyncio", "email", "http",
              "xml"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
# The picture shown while the one file unpacks itself, before Python starts (installer.py closes it).
splash = Splash(os.path.join(BUILD, "setup-splash.png"), binaries=analysis.binaries, datas=analysis.datas,
                text_pos=None, always_on_top=False)
EXE(pyz, analysis.scripts, splash, splash.binaries, analysis.binaries, analysis.datas, [], name="OpenDMTQ-Setup",
    console=False, icon=os.path.join(BUILD, "OpenDMTQ.ico"), version=os.path.join(BUILD, "setup-version-info.txt"),
    upx=False)
