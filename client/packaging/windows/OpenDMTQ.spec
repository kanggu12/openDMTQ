# PyInstaller recipe for the Windows launcher: one folder with two programs that share it.
#   OpenDMTQ.exe      the window (no console), the one the installer's shortcuts start
#   OpenDMTQ-cmd.exe  the same program with a console, for --status, --play, --set and the others
# Run by client/packaging/windows/build.sh inside the Wine build container, from client/ in the repository.
import os

ROOT = os.path.abspath(".")
BUILD = os.environ.get("OPENDMTQ_BUILD_DIR", os.path.join(ROOT, "build", "windows"))

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "entry.py")],
    pathex=[ROOT],
    # Fonts and their licences travel with the launcher (theme.py looks for them next to itself); the version and
    # where releases are published (empty when the build was given none), which __init__.py and updates.py read.
    datas=[(os.path.join(ROOT, "opendmtq_client", "assets"), os.path.join("opendmtq_client", "assets")),
           (os.path.join(BUILD, "version.txt"), "opendmtq_client"),
           (os.path.join(BUILD, "update-source.txt"), "opendmtq_client")],
    # Pillow finds Tk through this module at run time; PyInstaller cannot see that import.
    hiddenimports=["PIL._tkinter_finder"],
    # Nothing the launcher never uses: smaller and faster to start.
    excludes=["unittest", "pydoc", "test", "lib2to3", "idlelib"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
icon = os.path.join(BUILD, "OpenDMTQ.ico")
window = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="OpenDMTQ", console=False, icon=icon,
             version=os.path.join(BUILD, "version-info.txt"))
console = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="OpenDMTQ-cmd", console=True, icon=icon,
              version=os.path.join(BUILD, "version-info.txt"))
COLLECT(window, console, analysis.binaries, analysis.datas, name="OpenDMTQ")
