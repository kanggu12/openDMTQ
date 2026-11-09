# Licence texts for the PC client

`build.sh` puts these into the installed program's `licenses` folder, with the texts it takes from the build machine
(Python's, Tk's, Pillow's, PyInstaller's) and from the repository (OpenDMTQ's, the fonts'). These three are not on the
build machine, so they are kept here, unchanged from their projects:

| File | What it covers | From |
|---|---|---|
| `Velopack-LICENSE.txt` | Velopack: the installer's setup, `Update.exe`, the launcher's updates | Velopack's `LICENSE` at the commit its 1.2.161 release names |
| `libffi-LICENSE.txt` | libffi 3.4.4, in Python's `ctypes` | libffi's `LICENSE` at its tag `v3.4.4` |
| `zlib-LICENSE.txt` | zlib 1.3.1, in Python's `zlib` | zlib's `LICENSE` at its tag `v1.3.1` |
