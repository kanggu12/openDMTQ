# License and notice

For everyone who runs an OpenDMTQ server, plays on one, or works on the code. It is not legal advice. The site's
footers say what the project is and that the project acts on rights holders' requests.

## The project

OpenDMTQ is an unofficial, non-commercial community project. It is not affiliated with or endorsed by
NEOWIZ. DJMAX and TECHNIKA Q are trademarks of NEOWIZ, and the game is NEOWIZ's copyrighted work.

OpenDMTQ is a server framework. The repository contains no game data: no game client, songs, charts, images or
videos. A server runs only with files its owner provides: their own copy of the game's Android app (APK) and its client
data, which the game cannot start without. Songs are imported separately; a server without them starts the game with
an empty song list. What the repository does hold is OpenDMTQ's own code and what it takes to work with those files:
the names of the game's requests and files and the shapes of the replies the client reads, the short byte patterns and
addresses that `tools/opendmtq_tools/patch_apk.py` looks for in the client.

## For rights holders

This project respects the rights of NEOWIZ and other rights holders. If a rights holder asks, the repository
will promptly be made private or taken down, in whole or in the part concerned. No lawsuit or formal notice is
needed: a request in the repository's issues is enough, saying who is asking and what it concerns. The
maintainer can act on this repository's own contents; about a fork, another copy or a particular server, please
contact whoever runs it.

## License

OpenDMTQ's own code and documentation are under the MIT License: see [LICENSE](../LICENSE).

The license does not cover the game or its files (client, songs, charts, images, videos). Those are not in
the repository and are not licensed by it.

Nor does it cover third-party parts, which keep their own licenses:

| Part | Where | License |
| :--- | :--- | :--- |
| The site's fonts, cut down from Saira and Pretendard | `server/portal/fonts` | SIL Open Font License 1.1 (`server/portal/fonts/README.md`) |
| hls.js 1.5.17, the video player | `server/portal/hls` | Apache License 2.0 (`server/portal/hls/LICENSE`) |
| Dynarmic, the arm32 runtime's CPU emulator | Fetched by `arm32/build.sh`, built into the runtime and into the player for Windows; local changes in `arm32/patches` | 0BSD (its `LICENSE.txt`). The libraries it brings along (fmt, mcl, oaknut, robin-map, xbyak, Zydis and others) have their own. |
| Android's 32-bit linker and system libraries (libc, libm, libdl, libstdc++, libc++, libz, liblog), unchanged | Taken by `arm32/build.sh` from Google's Android 6.0 ARM system image (`armeabi-v7a-23_r06`). They are in the runtime a release hands out (`opendmtq-arm32-runtime.zip`) and in its player for Windows (`opendmtq-player-windows.zip`, under `runtime/sysroot`), which the PC client's installer (`OpenDMTQ-Setup.exe`) carries; and so in the tools image and the Windows bundle (which keep both, for app builds and for the site to hand out), and in every app built with the runtime | Open source, from the Android Open Source Project: Apache License 2.0, and BSD, MIT, ISC, zlib and NCSA licenses. The image's own terms leave such parts to their licenses (Android Software Development Kit License Agreement, 3.5). Their notices are the image's `etc/NOTICE.html.gz`, which goes with them; it does not name libc++, whose license is `arm32/libc++-LICENSE.txt`. The compiler's runtime in them (libgcc) is under the GCC Runtime Library Exception, which asks nothing of what is built with it |
| The player for Windows: ANGLE (`libEGL.dll`, `libGLESv2.dll`), zlib (`zlib1.dll`), the GCC runtime ANGLE's DLLs were built with (`libgcc_s_seh-1.dll`, `libstdc++-6.dll`), winpthreads (`libwinpthread-1.dll`), and, built into the player, LLVM's libc++, libc++abi, libunwind and compiler-rt and the mingw-w64 runtime with its winpthreads (llvm-mingw), and the picture's passes: AMD FidelityFX Super Resolution 1, NVIDIA Image Scaling, SMAA and Intel's CMAA 2, ported to OpenGL ES shaders; and the fonts of what it draws over the game, Pretendard and DMTQ Wide (a cut of Saira) | ANGLE, zlib, the GCC runtime and `libwinpthread-1.dll` from MSYS2's packages at fixed hashes (`arm32/build_windows.sh`); the rest from the llvm-mingw toolchain. The fonts are the PC client's, which `arm32/bundle_windows.sh` copies into the player's `fonts` folder. In the player a release hands out (`opendmtq-player-windows.zip`) and in the PC client's installer that carries it (`OpenDMTQ-Setup.exe`), which the tools image and the Windows bundle keep for the site to hand out. The app holds none of them | ANGLE: BSD 3-clause. zlib: zlib license. The GCC runtime: GPL 3 with the GCC Runtime Library Exception, which asks nothing of what is built with it. winpthreads and the mingw-w64 runtime: their own permissive licenses. LLVM: Apache License 2.0 with LLVM Exceptions. FSR 1, NIS and SMAA: MIT License. CMAA 2: Apache License 2.0 (`arm32/desktop/third_party`). The fonts: SIL Open Font License 1.1. The player carries every text in `licenses/NOTICES.txt` |
| The PC client: Python 3.12 with the Microsoft C runtime it ships, Tcl/Tk, OpenSSL, libffi and zlib in Python's modules, Pillow, Velopack, PyInstaller's bootloader, and the fonts DMTQ Wide (a cut of Saira), Pretendard and Material Icons | Built by `client/packaging/windows/build.sh` into the installer (`OpenDMTQ-Setup.exe`) and the program it installs, with the player above. A release hands it out, and the tools image and the Windows bundle keep it for the site to hand out. The app holds none of them | Python: PSF License, with bzip2's and Tcl/Tk's terms, and Microsoft's for its C runtime. Tcl/Tk: its BSD-style license. OpenSSL: Apache License 2.0. libffi: MIT. zlib: zlib license. Pillow: MIT-CMU, with the licenses of the image libraries in it. Velopack: MIT. PyInstaller's bootloader: GPL 2 with the Bootloader Exception, which allows it in a program under any license. The fonts: SIL Open Font License 1.1, and Apache License 2.0 for Material Icons. The installed program carries every text in `licenses/`, with `NOTICES.txt` saying which is whose, and the player's in `player/licenses/` |
| 7-Zip 25.01, Apktool 2.12.1, uber-apk-signer 1.3.0 | Fetched into the tools image by `tools/Dockerfile`, and into `.host/` by `host/install.sh`. The app holds none of them | 7-Zip: GNU LGPL with the unRAR restriction (its `License.txt` is in the image at `/usr/local/share/doc/7-zip` and in `.host/share/7-zip`, its source at 7-zip.org). The other two: Apache License 2.0 (inside their jars) |
| The container images a release publishes (`opendmtq-server`, `opendmtq-tools`) | Built on the official `php:8.3-apache` and `eclipse-temurin:21-jre-noble` images, with their systems' packages: PHP and the Apache HTTP Server, Python with Flask, gunicorn, qrcode, Pillow and lz4 | Each its own: PHP License 3.01, Apache License 2.0, GPL v2 with the Classpath Exception, PSF License, BSD, MIT and HPND. The packages' copyright files are in each image under `/usr/share/doc` |
| Apache HTTP Server 2.4.69 (Apache Lounge build), PHP 8.3.36, Python 3.12.10 with the Microsoft C runtime it ships, Eclipse Temurin 21 (Java), 7-Zip 25.01, Apktool, uber-apk-signer and the Python libraries of `host/windows/requirements.txt` | In the Windows bundle (`runtime/`), unchanged, as `host/windows/build.sh` downloads them. The bundle also holds the arm32 runtime (`app/tools/opendmtq_tools/opendmtq-arm32-runtime.zip`, with its licenses inside) | Each its own: Apache License 2.0, PHP License 3.01, PSF License, GPL v2 with the Classpath Exception (source at github.com/adoptium/jdk21u), GNU LGPL with the unRAR restriction, BSD, MIT and ZPL. The bundle's `THIRD-PARTY-NOTICES.txt` says where each full text is |

Those terms apply to whoever hands the runtime on or shares an app built with it. To make that simple, every app built with
the runtime carries the full texts in `assets/opendmtq` (`NOTICES.txt`, and Android's own `android-NOTICE.html.gz`), and
every server lists the parts at `/opendmtq/licenses.php`, linked from the site's footer.

## If you run a server

- OpenDMTQ works with game files you provide; it does not come with any. Please use files you have the right to
  use, within the rules that apply where you are. They stay on your server: the import keeps them in its `data/`
  folder.
- Players get the app and the songs from your server, with the accounts you make on the admin pages. Broadcasts and
  recordings stay off until you switch them on, and you can remove them at any time.
- If a rights holder asks you to take something down, please do so.

## If you play

- For questions about a server, please ask the person who runs it.

## Developers and contributors

- The software is provided "as is", without warranty of any kind, as the license states. To the fullest
  extent the law allows, the authors and contributors are not liable for any claim, damages or other
  liability arising from it or from how anyone uses it.
- Authors and contributors do not supply game files, do not tell anyone where to get them, and do not grant
  any right to use them.
- Each server is run independently by its own owner. This project is not a service and does not run servers
  on anyone's behalf.
- Please use, run and change this software in line with copyright law, the game's terms and the laws where you
  live, and only with game files you have the right to use.
- Contributions come in under the same license.
